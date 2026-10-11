"""Scope external verdicts to the audio, counterpart and Symptom actually compared."""

import hashlib

from abar.app.command_support import CommandError
from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from abar.compare.models import AudioObject
from abar.compare.operands import OperandResolution
from abar.compare.service import PreparedComparison
from abar.research.verification import VerificationReport

_ALWAYS_REJECT = {"exp.provenance.match", "exp.region.excerpt_from_full", "exp.baseline.reproduce"}
_BEST_REJECT = {"exp.sources.distinct", "exp.candidate.acted_on_target", "exp.candidate.no_op"}
_KNOWN = _ALWAYS_REJECT | _BEST_REJECT | {"exp.output.measured_is_final", "exp.control.matched"}


def verification_warnings(
    repository: WorkspaceRepository,
    state: ABARState,
    built: PreparedComparison,
    *,
    update_best: bool,
    symptom_id: str | None,
    same_check: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    for resolution, counterpart in ((built.left, built.right), (built.right, built.left)):
        provenance = resolution.operand.provenance_ref
        variant = str(provenance["variant_ref"])
        material = str(provenance["material_id"])
        against = str(counterpart.operand.provenance_ref["variant_ref"])
        report = next(
            (
                report
                for report in reversed(tuple(state.research.verifications.values()))
                if report.variant_id == variant and report.material_id == material
            ),
            None,
        )
        if report is None:
            continue
        if not _matches_audio(repository, state, resolution, report):
            raise CommandError(
                "verification_audio_mismatch",
                f"verification does not describe the current full render: {variant}/{material}",
            )
        for check in report.checks:
            if check.verdict != "fail" or check.id not in _KNOWN:
                continue
            if check.against is not None and check.against != against:
                continue
            if check.symptom_id is not None and check.symptom_id != symptom_id and not update_best:
                continue
            if check.id in _ALWAYS_REJECT or (update_best and check.id in _BEST_REJECT):
                raise CommandError(
                    "verification_failed", f"{check.id} failed for {variant}/{material}"
                )
            if check.id == "exp.control.matched" and update_best:
                continue
            if check.id == "exp.sources.distinct" and same_check:
                continue
            warnings.append(f"{check.id}: fail ({variant}/{material})")
    return tuple(dict.fromkeys(warnings))


def _matches_audio(
    repository: WorkspaceRepository,
    state: ABARState,
    resolution: OperandResolution,
    report: VerificationReport,
) -> bool:
    # Resolve the full output, never a standalone excerpt or the Recipe output.
    candidates: list[AudioObject] = []
    for effect in resolution.effects:
        if effect.kind == "render":
            candidates.append(effect.audio)
        if effect.kind == "slice" and effect.source_audio_id in state.compare.audio:
            candidates.append(state.compare.audio[effect.source_audio_id])
    for effect in resolution.effects:
        if effect.kind == "slice":
            candidates.extend(
                item.audio for item in resolution.effects if item.audio.id == effect.source_audio_id
            )
    return any(
        f"sha256:{hashlib.sha256(repository.objects.read(audio.object_id)).hexdigest()}"
        == report.final_wav_sha256
        for audio in candidates
    )
