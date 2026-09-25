import type { ReactNode } from "react";

/* エラーの帯: nibi の alert(印と語。色だけで伝えない、SPEC §3.4.2)。 */
export function InlineError({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={`nibi-alert nibi-alert--banner inline-error${className ? ` ${className}` : ""}`} role="alert">
      <span className="nibi-alert__icon" aria-hidden="true" />
      <span className="nibi-alert__text">{children}</span>
    </p>
  );
}
