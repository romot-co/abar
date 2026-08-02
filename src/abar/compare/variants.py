"""Variant registration rules independent of application persistence."""

from dataclasses import dataclass

from abar.compare.manifests import VariantManifest, variant_id
from abar.compare.models import Variant
from abar.foundation.json_types import JSONValue


@dataclass(frozen=True, slots=True)
class VariantRegistration:
    variant: Variant
    manifest: VariantManifest
    provenance: dict[str, JSONValue] | None


def register_variant(
    manifest_document: dict[str, JSONValue],
    *,
    resolved_params: dict[str, JSONValue] | None = None,
    label: str | None = None,
    provenance: dict[str, JSONValue] | None = None,
) -> VariantRegistration:
    manifest = VariantManifest.model_validate(manifest_document)
    params = resolved_params or {}
    variant = Variant(
        id=variant_id(manifest.id, params),
        label=label,
        manifest_id=manifest.id,
        resolved_params=params,
        render_contract=manifest.render_contract,
    )
    return VariantRegistration(variant=variant, manifest=manifest, provenance=provenance)
