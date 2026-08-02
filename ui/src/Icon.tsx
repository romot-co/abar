import type { ReactNode } from "react";

export type IconName = "arrow_back" | "pause" | "play_arrow" | "unfold_more";

/* Material Iconsのリガチャフォント代替。24pxグリッドのstrokeアイコン(Lucide系)。
   アイコンは機能を持つもの(戻る・再生/停止・ピッカー開閉)に限る。装飾には使わない。 */
const PATHS: Record<IconName, ReactNode> = {
  arrow_back: (
    <>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </>
  ),
  pause: (
    <>
      <rect x="14" y="4" width="4" height="16" rx="1" />
      <rect x="6" y="4" width="4" height="16" rx="1" />
    </>
  ),
  play_arrow: <path d="m6 3 14 9-14 9z" fill="currentColor" />,
  unfold_more: (
    <>
      <path d="m7 15 5 5 5-5" />
      <path d="m7 9 5-5 5 5" />
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
