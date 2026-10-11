import { moveEndpoint, rangeText, type LoopRange } from "./loopRange";
import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";

/*
 * 再生位置: nibi のスライダー行の位置の形(`.nibi-slider--position`、slider.md M-1)を1行(`--bare`)で。
 * 値はReactが持つ(nibi の DOM 初期化は使わない)。操作は nibi SPEC §7 に従う:
 *   レール上の押下 = その位置へ、ドラッグ = 相対(Shift で 1/10)、矢印 = 1 ステップ(Shift で 1/10)、
 *   PageUp / PageDown = 10%、Home / End = 最初・最後。位置の形なのでダブルクリックで戻さない。
 * 支援技術には role="slider" と、読める時刻(aria-valuetext)を渡す。
 */

type Props = {
  position: number;
  duration: number;
  disabled: boolean;
  onSeek: (seconds: number) => void;
  loop?: LoopRange | null;
  loopDuration?: number;
  onLoopChange?: (range: LoopRange) => void;
};

type Drag = { pointerId: number; lastX: number; span: number; value: number };

export function PositionSlider({ position, duration, disabled, onSeek, loop = null, loopDuration = duration, onLoopChange }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLSpanElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const [grabbed, setGrabbed] = useState(false);
  const max = Math.max(duration, 0);
  const at = max > 0 ? Math.min(Math.max(position / max, 0), 1) : 0;
  const readout = `${formatTime(position)} / ${formatTime(duration)}`;
  const seek = (seconds: number) => onSeek(Math.min(Math.max(seconds, 0), max));

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0 || max <= 0) return;
    const rail = railRef.current?.getBoundingClientRect();
    if (!rail || rail.width <= 0) return;
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* the pointer is already gone */ }
    // 1行の形ではレール行が行全体: 押した位置へ絶対に動かし、そのままドラッグを続けられる。
    const value = ((event.clientX - rail.left) / rail.width) * max;
    dragRef.current = { pointerId: event.pointerId, lastX: event.clientX, span: rail.width, value: Math.min(Math.max(value, 0), max) };
    setGrabbed(true);
    seek(value);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const delta = event.clientX - drag.lastX;
    drag.lastX = event.clientX;
    if (delta === 0) return;
    const fine = event.shiftKey ? interaction(rootRef.current, "--nibi-interaction-fine-factor", 0.1) : 1;
    drag.value = Math.min(Math.max(drag.value + (delta / drag.span) * max * fine, 0), max);
    seek(drag.value);
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setGrabbed(false);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || event.altKey || event.ctrlKey || event.metaKey) return;
    // Spaceは頁を送らない(A/B切替は他の場所で。フォーカス中の操作子の上では何もしない)。
    if (event.key === " ") { event.preventDefault(); return; }
    const root = rootRef.current;
    const step = interaction(root, "--nibi-interaction-step", 0.01);
    const page = interaction(root, "--nibi-interaction-page-step", 0.1);
    const fine = event.shiftKey ? interaction(root, "--nibi-interaction-fine-factor", 0.1) : 1;
    const moves: Record<string, number> = { ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step, PageUp: page, PageDown: -page };
    let next: number | null = null;
    const move = moves[event.key];
    if (move !== undefined) next = position + move * fine * max;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = max;
    if (next === null) return;
    event.preventDefault();
    seek(next);
  };

  const style = { "--nibi-value": at, "--nibi-fill-from": 0, "--nibi-fill-to": at, "--nibi-readout-width": "auto", "--loop-from": loop ? loop.start / max : 0, "--loop-to": loop ? loop.end / max : 1 } as CSSProperties;
  return (
    <div
      ref={rootRef}
      className={`nibi-slider nibi-slider--position nibi-slider--bare position-slider${grabbed ? " nibi-is-grabbed" : ""}`}
      style={style}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onKeyDown={onKeyDown}
    >
      <span className="position-seek nibi-slider--position"
      role="slider"
      tabIndex={disabled ? undefined : 0}
      aria-label="再生位置"
      aria-valuemin={0}
      aria-valuemax={Number(max.toFixed(2))}
      aria-valuenow={Number(Math.min(Math.max(position, 0), max).toFixed(2))}
      aria-valuetext={readout}
      aria-disabled={disabled || undefined}
      />
      <span className="nibi-slider__label">再生位置</span>
      <span className="nibi-slider__value nibi-value time" aria-hidden="true">{readout}</span>
      <span ref={railRef} className="nibi-slider__rail">
        <span className="nibi-slider__fill" />
        {loop && onLoopChange && <>
          <span className="loop-band" aria-hidden="true" />
          {(["start", "end"] as const).map((endpoint) => <LoopHandle key={endpoint} endpoint={endpoint} range={loop} duration={loopDuration} disabled={disabled} railRef={railRef} onChange={onLoopChange} />)}
        </>}
        <span className="nibi-slider__thumb" />
      </span>
    </div>
  );
}

function interaction(element: Element | null, name: string, fallback: number): number {
  if (!element) return fallback;
  const value = Number.parseFloat(getComputedStyle(element).getPropertyValue(name));
  return Number.isFinite(value) ? value : fallback;
}

function formatTime(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${Math.floor(safe % 60).toString().padStart(2, "0")}`;
}

function LoopHandle({ endpoint, range, duration, disabled, railRef, onChange }: {
  endpoint: "start" | "end"; range: LoopRange; duration: number; disabled: boolean;
  railRef: { current: HTMLSpanElement | null }; onChange: (value: LoopRange) => void;
}) {
  const drag = useRef<Drag | null>(null);
  const move = (value: number) => onChange(moveEndpoint(range, endpoint, value, duration));
  const endDrag = () => { drag.current = null; };
  return <span className={`loop-handle loop-handle--${endpoint}`} role="slider" tabIndex={disabled ? -1 : 0}
    aria-label={`ループ範囲 ${endpoint === "start" ? "始点" : "終点"}`} aria-valuemin={endpoint === "start" ? 0 : range.start + Math.min(0.25, duration)}
    aria-valuemax={endpoint === "start" ? range.end - Math.min(0.25, duration) : duration} aria-valuenow={range[endpoint]} aria-valuetext={rangeText(range)} aria-disabled={disabled || undefined}
    onPointerDown={(event) => {
      event.stopPropagation();
      if (disabled || event.button !== 0) return;
      const rail = railRef.current?.getBoundingClientRect();
      if (!rail || rail.width <= 0) return;
      event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointerId: event.pointerId, lastX: event.clientX, span: rail.width, value: range[endpoint] };
    }}
    onPointerMove={(event) => {
      event.stopPropagation(); const current = drag.current;
      if (!current || current.pointerId !== event.pointerId) return;
      current.value += (event.clientX - current.lastX) / current.span * duration * (event.shiftKey ? 0.1 : 1);
      current.lastX = event.clientX;
      current.value = moveEndpoint(range, endpoint, current.value, duration)[endpoint];
      move(current.value);
    }}
    onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}
    onKeyDown={(event) => {
      if (disabled || event.altKey || event.ctrlKey || event.metaKey) return;
      const steps: Record<string, number> = { ArrowLeft: -0.01, ArrowDown: -0.01, ArrowRight: 0.01, ArrowUp: 0.01, PageDown: -0.1, PageUp: 0.1 };
      const step = steps[event.key];
      if (step !== undefined) { event.stopPropagation(); event.preventDefault(); move(range[endpoint] + step * duration * (event.shiftKey ? 0.1 : 1)); }
      else if (event.key === "Home" || event.key === "End") { event.stopPropagation(); event.preventDefault(); move(event.key === "Home" ? 0 : duration); }
      else if (event.key === " ") event.preventDefault();
    }} />;
}
