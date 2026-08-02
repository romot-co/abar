"""Validated append-only event envelopes."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field

from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue

NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: NonEmptyString
    event_type: NonEmptyString
    schema_version: Annotated[int, Field(ge=1)] = 1
    ts: AwareDatetime
    causation_id: NonEmptyString | None = None
    idempotency_key: NonEmptyString
    payload: dict[str, JSONValue]

    @computed_field
    @property
    def payload_hash(self) -> str:
        return f"sha256:{canonical_sha256(self.payload)}"


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_seq: Annotated[int, Field(ge=1)]
    event_id: NonEmptyString
    event_type: NonEmptyString
    schema_version: Annotated[int, Field(ge=1)]
    ts: AwareDatetime
    causation_id: NonEmptyString | None = None
    idempotency_key: NonEmptyString
    payload_hash: Sha256Digest
    payload: dict[str, JSONValue]
