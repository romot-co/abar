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
};

type Drag = { pointerId: number; lastX: number; span: number; value: number };

export function PositionSlider({ position, duration, disabled, onSeek }: Props) {
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

  const style = { "--nibi-value": at, "--nibi-fill-from": 0, "--nibi-fill-to": at, "--nibi-readout-width": "auto" } as CSSProperties;
  return (
    <div
      ref={rootRef}
      className={`nibi-slider nibi-slider--position nibi-slider--bare position-slider${grabbed ? " nibi-is-grabbed" : ""}`}
      role="slider"
      tabIndex={disabled ? undefined : 0}
      aria-label="再生位置"
      aria-valuemin={0}
      aria-valuemax={Number(max.toFixed(2))}
      aria-valuenow={Number(Math.min(Math.max(position, 0), max).toFixed(2))}
      aria-valuetext={readout}
      aria-disabled={disabled || undefined}
      style={style}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onKeyDown={onKeyDown}
    >
      <span className="nibi-slider__label">再生位置</span>
      <span className="nibi-slider__value nibi-value time" aria-hidden="true">{readout}</span>
      <span ref={railRef} className="nibi-slider__rail">
        <span className="nibi-slider__fill" />
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

export function formatTime(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${Math.floor(safe % 60).toString().padStart(2, "0")}`;
}
