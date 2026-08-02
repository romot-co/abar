"""Deterministic default Material clip selection."""

from dataclasses import dataclass

import numpy as np

from abar.compare.audio.content import DecodedAudio
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue

SELECTOR_ID = "activity-transient-low-v2"
SELECTOR_VERSION = 2
WINDOW_SECONDS = 4


@dataclass(frozen=True, slots=True)
class SelectedWindow:
    start_frame: int
    frames: int
    role: str
    selector_id: str = SELECTOR_ID
    selector_version: int = SELECTOR_VERSION
    seed: int = 0


def select_default_clips(audio: DecodedAudio, *, seed: int = 0) -> tuple[SelectedWindow, ...]:
    window_frames = WINDOW_SECONDS * audio.sample_rate
    if audio.frames <= window_frames:
        return (SelectedWindow(0, audio.frames, "whole", seed=seed),)
    mono = np.mean(audio.pcm.astype(np.float64), axis=1)
    analysis = max(1, round(0.4 * audio.sample_rate))
    hop = max(1, round(0.1 * audio.sample_rate))
    starts = np.arange(0, audio.frames - analysis + 1, hop, dtype=np.int64)
    rms = np.array(
        [float(np.sqrt(np.mean(np.square(mono[start : start + analysis])))) for start in starts]
    )
    representative = int(np.argmin(np.abs(rms - np.quantile(rms, 0.75))))
    transient = int(np.argmax(np.maximum(np.diff(rms, prepend=rms[0]), 0.0)))
    threshold = max(float(np.max(rms)) * 1e-3, 1e-7)
    active = np.flatnonzero(rms >= threshold)
    low = int(active[np.argmin(rms[active])]) if active.size else representative
    output: list[SelectedWindow] = []
    used: set[int] = set()
    for role, index in (
        ("representative", representative),
        ("transient", transient),
        ("low_level", low),
    ):
        center = int(starts[index]) + analysis // 2
        start = min(max(center - window_frames // 2, 0), audio.frames - window_frames)
        if start in used:
            continue
        used.add(start)
        output.append(SelectedWindow(start, window_frames, role, seed=seed))
    return tuple(output)


def clip_id(material: str, window: SelectedWindow) -> str:
    identity: dict[str, JSONValue] = {
        "material_id": material,
        "start_frame": window.start_frame,
        "frames": window.frames,
        "role": window.role,
        "selector_id": window.selector_id,
        "selector_version": window.selector_version,
        "seed": window.seed,
    }
    return f"clip_{canonical_sha256(identity)}"


def manual_clip_id(material: str, start_frame: int, frames: int, role: str | None) -> str:
    identity: dict[str, JSONValue] = {
        "material_id": material,
        "start_frame": start_frame,
        "frames": frames,
        "role": role,
    }
    return f"clip_{canonical_sha256(identity)}"
