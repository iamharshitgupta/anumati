"""Document store with two interchangeable backends.

* ``FirestoreStore`` — production backend on Cloud Run. Collections map 1:1 to
  Firestore collections so the Firebase console can attach realtime listeners
  (``onSnapshot``) directly to ``decisions``, ``stepups`` and ``receipts``.
* ``MemoryStore`` — in-process dict store for local demos, CI and the eval suite.

The interface is deliberately tiny so the two stay in lock-step.
"""

from __future__ import annotations

import copy
import operator
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

Filter = tuple[str, str, Any]  # (field, op, value); op in ==, !=, <, <=, >, >=, in, array_contains

_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "in": lambda a, b: a in b,
    "array_contains": lambda a, b: isinstance(a, list) and b in a,
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseStore:
    def create(self, collection: str, doc_id: str, doc: dict) -> dict:
        """Create once; return the existing document without overwriting it."""
        raise NotImplementedError

    def put(self, collection: str, doc_id: str, doc: dict) -> dict:  # full write
        raise NotImplementedError

    def get(self, collection: str, doc_id: str) -> dict | None:
        raise NotImplementedError

    def update(self, collection: str, doc_id: str, patch: dict) -> dict:  # merge
        raise NotImplementedError

    def query(
        self,
        collection: str,
        filters: Iterable[Filter] = (),
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        raise NotImplementedError

    def delete(self, collection: str, doc_id: str) -> None:
        raise NotImplementedError

    def clear(self) -> None:  # tests only
        raise NotImplementedError


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------
class MemoryStore(BaseStore):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.RLock()

    def create(self, collection, doc_id, doc):
        with self._lock:
            return self.get(collection, doc_id) or self.put(collection, doc_id, doc)

    def put(self, collection: str, doc_id: str, doc: dict) -> dict:
        with self._lock:
            d = copy.deepcopy(doc)
            d["id"] = doc_id
            self._data.setdefault(collection, {})[doc_id] = d
            return copy.deepcopy(d)

    def get(self, collection: str, doc_id: str) -> dict | None:
        with self._lock:
            d = self._data.get(collection, {}).get(doc_id)
            return copy.deepcopy(d) if d else None

    def update(self, collection: str, doc_id: str, patch: dict) -> dict:
        with self._lock:
            col = self._data.setdefault(collection, {})
            d = col.get(doc_id)
            if d is None:
                raise KeyError(f"{collection}/{doc_id} not found")
            d.update(copy.deepcopy(patch))
            return copy.deepcopy(d)

    def query(self, collection, filters=(), order_by=None, descending=False, limit=None):
        with self._lock:
            rows = list(self._data.get(collection, {}).values())
        for field, op, value in filters:
            fn = _OPS[op]
            rows = [r for r in rows if _has(r, field) and _safe(fn, _path(r, field), value)]
        if order_by:
            rows.sort(key=lambda r: (_path(r, order_by) is None, _path(r, order_by)), reverse=descending)
        if limit:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    def delete(self, collection, doc_id):
        with self._lock:
            self._data.get(collection, {}).pop(doc_id, None)

    def clear(self):
        with self._lock:
            self._data.clear()


def _path(doc: dict, dotted: str):
    """Firestore-style dotted field paths (``request.mandate_id``)."""
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _has(doc: dict, dotted: str) -> bool:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _safe(fn, a, b):
    try:
        return bool(fn(a, b))
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Firestore backend
# ---------------------------------------------------------------------------
class FirestoreStore(BaseStore):
    def __init__(self, project: str | None, database: str = "(default)") -> None:
        from google.cloud import firestore  # imported lazily so local mode has no dep

        self._fs = firestore
        self._client = firestore.Client(project=project, database=database)

    def create(self, collection, doc_id, doc):
        from google.api_core.exceptions import AlreadyExists

        d = {**doc, "id": doc_id}
        ref = self._client.collection(collection).document(doc_id)
        try:
            ref.create(d)
            return d
        except AlreadyExists:
            return ref.get().to_dict()

    def put(self, collection, doc_id, doc):
        d = dict(doc)
        d["id"] = doc_id
        self._client.collection(collection).document(doc_id).set(d)
        return d

    def get(self, collection, doc_id):
        snap = self._client.collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def update(self, collection, doc_id, patch):
        ref = self._client.collection(collection).document(doc_id)
        ref.set(dict(patch), merge=True)
        return ref.get().to_dict()

    def query(self, collection, filters=(), order_by=None, descending=False, limit=None):
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self._client.collection(collection)
        for field, op, value in filters:
            q = q.where(filter=FieldFilter(field, op, value))
        if order_by:
            q = q.order_by(
                order_by,
                direction=self._fs.Query.DESCENDING if descending else self._fs.Query.ASCENDING,
            )
        if limit:
            q = q.limit(limit)
        return [s.to_dict() for s in q.stream()]

    def delete(self, collection, doc_id):
        self._client.collection(collection).document(doc_id).delete()

    def clear(self):
        raise RuntimeError("refusing to clear a Firestore database")


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------
_store: BaseStore | None = None


def get_store() -> BaseStore:
    global _store
    if _store is None:
        from .config import settings

        if settings.store_backend == "firestore":
            _store = FirestoreStore(settings.gcp_project, settings.firestore_database)
        else:
            _store = MemoryStore()
    return _store


def set_store(store: BaseStore) -> None:  # tests
    global _store
    _store = store
