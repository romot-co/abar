from pathlib import Path

import pytest

from abar.infrastructure.object_store import ImmutableObjectStore, ObjectIntegrityError


def test_content_addressed_put_is_idempotent(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    first = store.put(b"same")
    second = store.put(b"same")
    assert first == second
    assert store.read(first.object_id) == b"same"


def test_corruption_is_detected(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    stored = store.put(b"expected")
    digest = stored.object_id.removeprefix("obj_")
    (tmp_path / "objects" / digest[:2] / digest[2:]).write_bytes(b"corrupt")
    with pytest.raises(ObjectIntegrityError):
        store.read(stored.object_id)
