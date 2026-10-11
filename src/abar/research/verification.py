"""External verification reports; ABAR records verdicts without calculating them."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from abar.foundation.json_types import JSONValue


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: Annotated[str, Field(min_length=1)]
    verdict: Literal["pass", "fail", "skip"]
    against: str | None = None
    symptom_id: str | None = None
    details: dict[str, JSONValue] = Field(default_factory=dict[str, JSONValue])


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1]
    producer: Annotated[str, Field(min_length=1)]
    variant_id: str
    material_id: str
    final_wav_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    checks: list[VerificationCheck]

    @model_validator(mode="after")
    def validate_unique_checks(self) -> "VerificationReport":
        keys = [(check.id, check.against, check.symptom_id) for check in self.checks]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate verification check scope")
        return self
