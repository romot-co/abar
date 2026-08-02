from typing import Protocol


class StoredObjectRef(Protocol):
    @property
    def object_id(self) -> str: ...

    @property
    def sha256(self) -> str: ...


class ObjectReader(Protocol):
    def read(self, object_id: str) -> bytes: ...


class ObjectStore(ObjectReader, Protocol):
    def put(self, data: bytes) -> StoredObjectRef: ...
