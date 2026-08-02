import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_OBJECT_ID_PATTERN = re.compile(r"^obj_([0-9a-f]{64})$")


class InvalidObjectIdError(ValueError):
    """Raised when an object ID is not a canonical ABAR content ID."""


class ObjectIntegrityError(RuntimeError):
    """Raised when stored bytes do not match their content address."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_id: str
    sha256: str
    size: int


class ImmutableObjectStore:
    """Immutable SHA-256 addressed file store for the single-writer runtime."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        object_id = f"obj_{digest}"
        final_path = self._path_for_digest(digest)
        self._ensure_bucket(final_path.parent)

        if final_path.exists():
            self._verify_file(final_path, digest)
            return StoredObject(object_id=object_id, sha256=digest, size=final_path.stat().st_size)

        descriptor, temporary_name = tempfile.mkstemp(
            dir=final_path.parent,
            prefix=".tmp-",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            self._verify_file(temporary_path, digest)
            if final_path.exists():
                self._verify_file(final_path, digest)
                temporary_path.unlink()
            else:
                os.replace(temporary_path, final_path)
            self._fsync_directory(final_path.parent)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

        return StoredObject(object_id=object_id, sha256=digest, size=len(data))

    def read(self, object_id: str) -> bytes:
        digest = self._parse_object_id(object_id)
        path = self._path_for_digest(digest)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(f"object does not exist: {object_id}") from None
        if hashlib.sha256(data).hexdigest() != digest:
            raise ObjectIntegrityError(f"object content does not match ID: {object_id}")
        return data

    def exists(self, object_id: str) -> bool:
        digest = self._parse_object_id(object_id)
        return self._path_for_digest(digest).is_file()

    def _path_for_digest(self, digest: str) -> Path:
        return self._root / digest[:2] / digest[2:]

    def _ensure_bucket(self, bucket: Path) -> None:
        if bucket.exists():
            if not bucket.is_dir():
                raise ObjectIntegrityError(f"object bucket is not a directory: {bucket.name}")
            return
        bucket.mkdir()
        self._fsync_directory(self._root)

    @staticmethod
    def _parse_object_id(object_id: str) -> str:
        match = _OBJECT_ID_PATTERN.fullmatch(object_id)
        if match is None:
            raise InvalidObjectIdError(f"invalid object ID: {object_id!r}")
        return match.group(1)

    @staticmethod
    def _verify_file(path: Path, expected_digest: str) -> None:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_digest:
            raise ObjectIntegrityError(f"stored object failed hash verification: {path.name}")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
