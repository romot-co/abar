"""Small deterministic signal-analysis helpers used by Compare Core."""

from dataclasses import dataclass

import numpy as np

from abar.compare.audio.content import DecodedAudio


@dataclass(frozen=True, slots=True)
class CommonRange:
    start_seconds: float
    duration_seconds: float
    algorithm_id: str = "common-active-range-v1"
    version: int = 1
    window_ms: int = 100
    hop_ms: int = 50
    floor_dbfs: float = -60.0
    relative_db: float = -40.0


def common_active_range(first: DecodedAudio, second: DecodedAudio) -> CommonRange:
    common_duration = min(
        first.frames / first.sample_rate,
        second.frames / second.sample_rate,
    )
    if common_duration < 5.0:
        raise ValueError("eligible_common_signal_too_short")
    frame_count = max(1, int(np.floor((common_duration - 0.1) / 0.05)) + 1)

    def active(audio: DecodedAudio) -> np.ndarray:
        window = max(1, round(audio.sample_rate * 0.1))
        hop = max(1, round(audio.sample_rate * 0.05))
        mono = np.mean(audio.pcm.astype(np.float64), axis=1)
        starts = np.arange(frame_count) * hop
        rms = np.array([float(np.sqrt(np.mean(np.square(mono[s : s + window])))) for s in starts])
        db = 20.0 * np.log10(np.maximum(rms, 1e-12))
        return db >= max(-60.0, float(np.max(db)) - 40.0)

    common = active(first) & active(second)
    best_start = best_end = run_start = 0
    running = False
    for index, value in enumerate(common):
        if value and not running:
            run_start = index
            running = True
        if running and (not value or index == len(common) - 1):
            run_end = index if not value else index + 1
            if run_end - run_start > best_end - best_start:
                best_start, best_end = run_start, run_end
            running = False
    duration = (best_end - best_start - 1) * 0.05 + 0.1 if best_end > best_start else 0.0
    if duration < 5.0:
        raise ValueError("eligible_common_signal_too_short")
    start = best_start * 0.05
    if duration > 30.0:
        start += (duration - 30.0) / 2.0
        duration = 30.0
    return CommonRange(start_seconds=start, duration_seconds=duration)
