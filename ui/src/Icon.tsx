import type { ReactNode } from "react";

export type IconName = "chevron_left" | "chevron_right" | "check" | "pause" | "play_arrow" | "warning";

/* Material Iconsのリガチャフォント代替。24pxグリッドのstrokeアイコン(Lucide系)。
   アイコンは機能か状態を持つもの(戻る・開閉・再生/停止・聴取済・問題あり)に限る。装飾には使わない。 */
const PATHS: Record<IconName, ReactNode> = {
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
  warning: (
    <>
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </>
  ),
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="ui-icon"
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
