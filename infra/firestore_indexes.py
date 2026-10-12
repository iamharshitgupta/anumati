"""Set up declared composite indexes in an existing cloud Firestore database.

Run this as a separate infrastructure step, not during API startup. It reuses
web/firestore.indexes.json, so local-cloud setup and deployment share the same
definitions. The project, database, and index file are configurable.

Usage from the repository root, with your Python environment activated:
    python -B infra/firestore_indexes.py --project YOUR_PROJECT_ID
    python -B infra/firestore_indexes.py --project YOUR_PROJECT_ID --apply --wait

The first command previews definitions offline without credentials or cloud
calls. The second uses Application Default Credentials (ADC) to create only
missing indexes and wait until all declared indexes are READY. Existing indexes,
including builds already in progress, are skipped; no indexes are deleted.
Existing indexes are matched only within the requested database and collection.
Builds can take several minutes. --timeout controls the readiness wait in
seconds (default: 600); a timeout does not cancel builds, and rerunning is safe.

Prerequisites for --apply:
    - Install backend/requirements.txt; its Firestore SDK includes the Admin client.
    - Enable firestore.googleapis.com and create a Standard, Native-mode database.
    - Configure ADC, e.g. gcloud auth application-default login. Its identity needs
      roles/datastore.indexAdmin or equivalent permissions in the target project.

The database defaults to (default); override it with --database DATABASE_ID.
Override the declaration file with --index-file /path/to/indexes.json. The
default file is found relative to this script, independent of your current folder.
Only ordered composite indexes with collection or collection-group scope are
supported. Unsupported definitions or field overrides fail before cloud access.

This command does not deploy services, enable APIs, create databases, change IAM
or security rules, seed application data, or call Gemini. Index storage still
contributes to Firestore usage. --apply refuses to run if FIRESTORE_EMULATOR_HOST
is set because this Admin command targets the cloud, not the emulator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.firestore_admin_v1 import FirestoreAdminClient, Index

DEFAULT_INDEX_FILE = Path(__file__).resolve().parents[1] / "web" / "firestore.indexes.json"


def load_indexes(path: Path) -> list[tuple[str, Index]]:
    """Validate the entire declaration before any cloud changes are possible."""
    with path.open() as file:
        document = json.load(file)
    if not isinstance(document, dict) or not isinstance(document.get("indexes"), list):
        raise ValueError("Index file must contain an 'indexes' array.")
    if document.get("fieldOverrides"):
        raise ValueError("Field overrides are not supported; use the Firebase CLI for those.")

    indexes = []
    for number, definition in enumerate(document["indexes"], 1):
        context = f"Index {number}"
        if not isinstance(definition, dict) or set(definition) - {"collectionGroup", "queryScope", "fields"}:
            raise ValueError(f"{context}: unsupported index definition.")
        collection = definition.get("collectionGroup")
        if not isinstance(collection, str) or not collection.strip() or "/" in collection:
            raise ValueError(f"{context}: collectionGroup must be a collection ID.")
        scope = definition.get("queryScope", "COLLECTION")
        if not isinstance(scope, str) or scope not in {"COLLECTION", "COLLECTION_GROUP"}:
            raise ValueError(f"{context}: unsupported queryScope {scope!r}.")
        fields = definition.get("fields")
        if not isinstance(fields, list) or not 2 <= len(fields) <= 100:
            raise ValueError(f"{context}: a composite index needs 2 to 100 fields.")

        converted = []
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"fieldPath", "order"}:
                raise ValueError(f"{context}: only ordered fields are supported.")
            field_path = field["fieldPath"]
            if not isinstance(field_path, str) or not field_path.strip():
                raise ValueError(f"{context}: fieldPath must be a non-empty string.")
            if not isinstance(field["order"], str) or field["order"] not in {"ASCENDING", "DESCENDING"}:
                raise ValueError(f"{context}: unsupported field order {field['order']!r}.")
            converted.append({"field_path": field_path, "order": field["order"]})
        indexes.append((collection, Index(query_scope=scope, fields=converted)))
    return indexes


def index_key(index: Index) -> tuple:
    """Match declared and stored definitions, including Firestore's tiebreaker."""
    fields = [(field.field_path, int(field.order), int(field.array_config)) for field in index.fields]
    # Firestore appends this tiebreaker even when the JSON declaration omits it.
    if fields and fields[-1][0] != "__name__":
        direction = next((order for _, order, _ in reversed(fields) if order), Index.IndexField.Order.ASCENDING)
        fields.append(("__name__", int(direction), 0))
    return int(index.query_scope), int(getattr(index, "api_scope", 0)), tuple(fields)


def describe_index(collection: str, index: Index) -> str:
    fields = ", ".join(f"{field.field_path} {Index.IndexField.Order(field.order).name}" for field in index.fields)
    return f"{collection} [{Index.QueryScope(index.query_scope).name}]: {fields}"


def list_existing(client: FirestoreAdminClient, database_path: str, collection: str) -> dict:
    parent = f"{database_path}/collectionGroups/{collection}"
    # Responses can include other collection groups with identical field layouts.
    prefix = f"{parent}/indexes/"
    return {index_key(index): index for index in client.list_indexes(parent=parent, timeout=30)
            if index.name.startswith(prefix)}


def wait_until_ready(client: FirestoreAdminClient, database_path: str, indexes: list, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        collections = dict.fromkeys(collection for collection, _ in indexes)
        existing = {collection: list_existing(client, database_path, collection) for collection in collections}
        pending = []
        for collection, wanted in indexes:
            actual = existing[collection].get(index_key(wanted))
            if actual is not None and actual.state == Index.State.NEEDS_REPAIR:
                raise RuntimeError(f"Index needs repair: {actual.name}. No indexes were deleted.")
            if actual is None or actual.state != Index.State.READY:
                pending.append(describe_index(collection, wanted))
        if not pending:
            print(f"READY: all {len(indexes)} declared indexes are usable.", flush=True)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Timed out waiting for indexes. Builds may still be running; rerun with --apply --wait.")
        print(f"WAIT: {len(pending)} index(es) are not READY yet.", flush=True)
        time.sleep(min(10, remaining))


def apply_indexes(client: FirestoreAdminClient, project: str, database: str, indexes: list) -> int:
    database_path = f"projects/{project}/databases/{database}"
    collections = dict.fromkeys(collection for collection, _ in indexes)
    existing = {collection: list_existing(client, database_path, collection) for collection in collections}
    created = 0
    for collection, wanted in indexes:
        key = index_key(wanted)
        actual = existing[collection].get(key)
        label = describe_index(collection, wanted)
        if actual is not None:
            if actual.state == Index.State.NEEDS_REPAIR:
                raise RuntimeError(f"Index needs repair: {actual.name}. No indexes were deleted.")
            print(f"SKIP ({Index.State(actual.state).name}): {label}", flush=True)
            continue
        parent = f"{database_path}/collectionGroups/{collection}"
        try:
            client.create_index(parent=parent, index=wanted, timeout=30)
            created += 1
            print(f"CREATE: {label}", flush=True)
        except AlreadyExists:
            print(f"SKIP (already exists, possibly created concurrently): {label}", flush=True)
        existing[collection][key] = Index(wanted, state=Index.State.CREATING)
    print(f"Submitted {created} new index build(s). Existing indexes were not changed or deleted.", flush=True)
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True, help="Explicit Google Cloud project ID; never inferred from gcloud.")
    parser.add_argument("--database", default="(default)", help="Existing database ID (default: %(default)s).")
    parser.add_argument("--index-file", type=Path, default=DEFAULT_INDEX_FILE, help="Firebase-format composite index JSON.")
    parser.add_argument("--apply", action="store_true", help="Create missing cloud indexes using ADC; otherwise preview offline.")
    parser.add_argument("--wait", action="store_true", help="With --apply, wait until all declared indexes are READY.")
    parser.add_argument("--timeout", type=float, default=600, help="Seconds to wait for readiness (default: %(default)s).")
    args = parser.parse_args(argv)
    if not args.project.strip() or "/" in args.project or not args.database.strip() or "/" in args.database:
        parser.error("Project and database must be IDs, not resource paths.")
    if args.wait and not args.apply:
        parser.error("--wait requires --apply; the default preview makes no cloud calls.")
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be a positive, finite number.")
    if args.apply and os.getenv("FIRESTORE_EMULATOR_HOST"):
        parser.error("This is a cloud-only admin command. Unset FIRESTORE_EMULATOR_HOST before using --apply.")

    try:
        indexes = load_indexes(args.index_file)
        print(f"Target: projects/{args.project}/databases/{args.database}", flush=True)
        if not args.apply:
            print("PREVIEW: desired indexes only; no credentials, cloud reads or writes. Existing cloud state is not checked.")
            for collection, index in indexes:
                print(describe_index(collection, index))
            print("Run again with --apply to create missing indexes; add --wait to verify readiness.")
            return 0
        if not indexes:
            print("No composite indexes declared; nothing to apply.")
            return 0
        client = FirestoreAdminClient()
        apply_indexes(client, args.project, args.database, indexes)
        if args.wait:
            wait_until_ready(client, f"projects/{args.project}/databases/{args.database}", indexes, args.timeout)
        else:
            print("Builds may still be running. Use --apply --wait to verify readiness before testing queries.")
        return 0
    except (OSError, ValueError, RuntimeError, GoogleAPICallError, DefaultCredentialsError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
