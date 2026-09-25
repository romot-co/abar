import type { ReactNode } from "react";

export type IconName = "chevron_down" | "chevron_left" | "chevron_right" | "check" | "pause" | "play_arrow";

/* Material Iconsのリガチャフォント代替。24pxグリッドのstrokeアイコン(Lucide系)。
   アイコンは機能か状態を持つもの(戻る・開閉・選択・再生/停止・聴いた)に限る。装飾には使わない。合否の印は Mark(nibi の mark)。 */
const PATHS: Record<IconName, ReactNode> = {
  chevron_down: <path d="m6 9 6 6 6-6" />,
  chevron_left: <path d="m15 18-6-6 6-6" />,
  chevron_right: <path d="m9 18 6-6-6-6" />,
  check: <path d="M20 6 9 17l-5-5" />,
  pause: (
    <>
      <rect x="14" y="4" width="4" height="16" rx="1" />
      <rect x="6" y="4" width="4" height="16" rx="1" />
    </>
  ),
  play_arrow: <path d="m6 3 14 9-14 9z" fill="currentColor" />,
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className ? `ui-icon ${className}` : "ui-icon"}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
