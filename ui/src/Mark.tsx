import type { ReactNode } from "react";

/* nibi の状態の印(mark.md): どの状態も同じ直径の円。中の絵で意味、色で重さ。必ず語と並べる。 */
export type MarkKind = "pass" | "fail" | "unknown";

const GLYPHS: Record<MarkKind, ReactNode> = {
  pass: <path className="nibi-mark__glyph" d="M3.6 6.2L5.3 7.9 8.5 4.4" />,
  fail: (
    <>
      <path className="nibi-mark__glyph" d="M6 3.2v3.3" />
      <circle className="nibi-mark__glyph" cx="6" cy="8.7" r=".2" />
    </>
  ),
  unknown: <path className="nibi-mark__glyph" d="M4.2 6h3.6" />,
};

export function Mark({ kind }: { kind: MarkKind }) {
  return (
    <svg className={`nibi-mark nibi-mark--${kind}`} viewBox="0 0 12 12" aria-hidden="true">
      <circle className="nibi-mark__disc" cx="6" cy="6" r="5.4" />
      {GLYPHS[kind]}
    </svg>
  );
}
