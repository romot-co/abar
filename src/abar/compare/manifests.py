"""Strict Variant manifest validation and content identities."""

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue

Sha = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SECRET = re.compile(r"SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY", re.I)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceArchive(_StrictModel):
    object_id: Annotated[str, Field(pattern=r"^obj_[0-9a-f]{64}$")]
    sha: Sha


class CommandRenderer(_StrictModel):
    argv: Annotated[list[str], Field(min_length=1)]
    cwd: str = "."
    env: dict[str, str] = Field(default_factory=dict[str, str])
    timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 120
    seed_mode: Literal["required", "none"] = "none"
    executable_sha: Sha

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("renderer cwd must be archive-relative")
        return value

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        executable = PurePosixPath(value[0])
        if executable.is_absolute() or ".." in executable.parts:
            raise ValueError("renderer executable must be archive-relative")
        required = {"{input_wav}", "{params_json}", "{output_wav}"}
        if not required.issubset(set(value)):
            raise ValueError("renderer argv must contain input, params, and output placeholders")
        return value

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if _ENV_NAME.fullmatch(name) is None:
                raise ValueError(f"invalid environment variable name: {name}")
            if _SECRET.search(name):
                raise ValueError(f"secret-like environment variable is forbidden: {name}")
        return value


class FiniteMapEntry(_StrictModel):
    audio_object_id: Annotated[str, Field(pattern=r"^audio_[0-9a-f]{64}$")]
    audio_sha: Sha
    sample_rate: Annotated[int, Field(gt=0)]
    channel_layout: Literal["mono", "stereo"]
    frames: Annotated[int, Field(gt=0)]


class Renderer(_StrictModel):
    kind: Literal["command", "finite_map"]
    context_policy: Literal["full_material"]
    timeline_policy: Literal["source_aligned_exact_v1"]
    command: CommandRenderer | None = None
    finite_map: dict[str, FiniteMapEntry] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "Renderer":
        if self.kind == "command" and (self.command is None or self.finite_map is not None):
            raise ValueError("command renderer requires only command configuration")
        if self.kind == "finite_map" and (self.finite_map is None or self.command is not None):
            raise ValueError("finite_map renderer requires only finite_map configuration")
        return self


class InputContract(_StrictModel):
    audio: Literal["canonical_wav"]
    params: Literal["canonical_json"]


class OutputContract(_StrictModel):
    container: Literal["wav"]
    sample_rates: Literal["source"]
    channel_layouts: Annotated[list[Literal["mono", "stereo"]], Field(min_length=1)]


class VariantManifest(_StrictModel):
    schema_version: Literal[1]
    source_archive: SourceArchive
    renderer: Renderer
    input_contract: InputContract
    output_contract: OutputContract

    def document(self) -> dict[str, JSONValue]:
        return self.model_dump(mode="json")  # type: ignore[return-value]

    @property
    def id(self) -> str:
        return f"vm_{canonical_sha256(self.document())}"

    @property
    def render_contract(self) -> Literal["renderable", "finite_rendered"]:
        return "renderable" if self.renderer.kind == "command" else "finite_rendered"


def variant_id(manifest_id: str, resolved_params: dict[str, JSONValue]) -> str:
    return f"v_{canonical_sha256({'manifest_id': manifest_id, 'resolved_params': resolved_params})}"
