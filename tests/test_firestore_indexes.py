import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from google.cloud.firestore_admin_v1 import Index

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infra import firestore_indexes as setup  # noqa: E402


def receipt_index(state=Index.State.READY):
    return Index(query_scope="COLLECTION", state=state, fields=[
        {"field_path": "mandate_id", "order": "ASCENDING"},
        {"field_path": "issued_at", "order": "DESCENDING"},
    ])


def test_offline_preview_reads_existing_definitions_from_any_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    client = Mock(side_effect=AssertionError("Preview must not access cloud credentials."))
    monkeypatch.setattr(setup, "FirestoreAdminClient", client)
    assert len(setup.load_indexes(setup.DEFAULT_INDEX_FILE)) == 7
    assert setup.main(["--project", "example-project"]) == 0
    client.assert_not_called()
    assert "PREVIEW" in capsys.readouterr().out


def test_apply_creates_missing_index_then_skips_existing_build():
    client = Mock()
    wanted = receipt_index()
    client.list_indexes.return_value = []
    assert setup.apply_indexes(client, "example-project", "demo", [("receipts", wanted)]) == 1
    client.create_index.assert_called_once_with(
        parent="projects/example-project/databases/demo/collectionGroups/receipts", index=wanted, timeout=30,
    )
    actual = receipt_index(state=Index.State.CREATING)
    actual.fields.append(Index.IndexField(field_path="__name__", order="DESCENDING"))
    client.list_indexes.return_value = [actual]
    assert setup.apply_indexes(client, "example-project", "demo", [("receipts", wanted)]) == 0
    assert client.create_index.call_count == 1


def test_apply_waits_until_ready(monkeypatch, capsys):
    client = Mock()
    client.list_indexes.side_effect = [[], [receipt_index(Index.State.CREATING)], [receipt_index()]]
    monkeypatch.setattr(setup, "load_indexes", Mock(return_value=[("receipts", receipt_index())]))
    monkeypatch.setattr(setup, "FirestoreAdminClient", Mock(return_value=client))
    sleep = Mock()
    monkeypatch.setattr(setup.time, "sleep", sleep)
    assert setup.main(["--project", "example-project", "--apply", "--wait"]) == 0
    assert client.create_index.call_count == 1
    sleep.assert_called_once()
    assert "READY: all 1" in capsys.readouterr().out


def test_invalid_definition_fails_before_cloud_access(tmp_path, monkeypatch):
    path = tmp_path / "indexes.json"
    path.write_text(json.dumps({"indexes": [{"collectionGroup": "receipts", "fields": []}]}))
    client = Mock()
    monkeypatch.setattr(setup, "FirestoreAdminClient", client)
    assert setup.main(["--project", "example-project", "--index-file", str(path), "--apply"]) == 1
    client.assert_not_called()


def test_readiness_timeout_does_not_cancel_builds(monkeypatch):
    client = Mock()
    client.list_indexes.return_value = [receipt_index(Index.State.CREATING)]
    monkeypatch.setattr(setup.time, "monotonic", Mock(side_effect=[0, 61]))
    with pytest.raises(RuntimeError, match="Builds may still be running"):
        setup.wait_until_ready(client, "projects/example-project/databases/demo", [("receipts", receipt_index())], 60)
    client.cancel_operation.assert_not_called()
