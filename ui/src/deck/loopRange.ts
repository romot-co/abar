export type LoopRange = { start: number; end: number };
export const LOOP_MIN_SECONDS = 0.25;

export function initialLoop(position: number, duration: number): LoopRange {
  const length = Math.min(1, duration);
  const start = Math.max(0, Math.min(position - length / 2, duration - length));
  return { start, end: start + length };
}

export function moveEndpoint(range: LoopRange, endpoint: "start" | "end", value: number, duration: number): LoopRange {
  const min = Math.min(LOOP_MIN_SECONDS, duration);
  return endpoint === "start"
    ? { start: Math.max(0, Math.min(value, range.end - min)), end: range.end }
    : { start: range.start, end: Math.max(range.start + min, Math.min(value, duration)) };
}

export function loopPosition(offset: number, elapsed: number, duration: number, loop: LoopRange | null): { position: number; cycle: number } {
  const start = loop?.start ?? 0;
  const end = loop?.end ?? duration;
  const length = end - start;
  if (length <= 0) return { position: offset, cycle: 0 };
  // A seek before the range is allowed by Web Audio; after loopEnd it wraps to loopStart.
  const absolute = offset + Math.max(0, elapsed);
  if (absolute < end) return { position: absolute, cycle: 0 };
  return { position: start + ((absolute - end) % length), cycle: 1 + Math.floor((absolute - end) / length) };
}

export function rangeText(range: LoopRange): string {
  return `${range.start.toFixed(2)} – ${range.end.toFixed(2)} s`;
}
