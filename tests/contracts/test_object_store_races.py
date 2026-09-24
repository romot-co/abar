from pathlib import Path

import pytest

from abar.infrastructure.object_store import (
    ImmutableObjectStore,
    ObjectIntegrityError,
    ObjectMissingError,
)


def test_bucket_created_by_a_concurrent_writer_does_not_fail_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    original = Path.mkdir

    def racing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        # Another writer creates the same bucket between the check and our mkdir.
        original(self, exist_ok=True)
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    stored = store.put(b"payload")
    monkeypatch.undo()

    assert store.read(stored.object_id) == b"payload"


def test_non_directory_bucket_is_still_an_integrity_error(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    probe = store.put(b"probe")
    digest = probe.object_id.removeprefix("obj_")
    bucket = tmp_path / "objects" / digest[:2]
    for child in bucket.iterdir():
        child.unlink()
    bucket.rmdir()
    bucket.write_bytes(b"not a directory")

    with pytest.raises(ObjectIntegrityError):
        store.put(b"probe")


def test_missing_object_has_a_dedicated_error(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    with pytest.raises(ObjectMissingError):
        store.read(f"obj_{'0' * 64}")
    assert issubclass(ObjectMissingError, FileNotFoundError)
