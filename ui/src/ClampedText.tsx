import { useId, useLayoutEffect, useRef, useState, type ElementType, type ReactNode } from "react";

/*
 * 長い問いを決まった行数で止め、「全文を表示」「たたむ」で開閉する(handoff: 受信箱の面 4行、結果の問い 3行、
 * Deckの問い 2行 / 480px 未満 3行)。行数はCSS(`--clamp-lines`)が持ち、止めたときに文があふれているかを
 * 実際の大きさで確かめる(文字数で決めない: 幅と文字で行数が変わる)。あふれていなければ開閉を出さない。
 * 止めている間も全文はDOMにあり、読み上げは全文を読む。
 */
export function ClampedText({ as: Tag = "p", className, id, children }: {
  as?: ElementType;
  className: string;
  id?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const autoId = useId();
  const textId = id ?? `clamp-${autoId}`;

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || expanded) return;
    const measure = () => setOverflowing(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [expanded, children]);

  return (
    <>
      <Tag ref={ref} id={textId} className={`${className} clamped-text`} data-expanded={expanded ? "" : undefined}>{children}</Tag>
      {(overflowing || expanded) && (
        <p className="clamp-controls">
          <button type="button" className="nibi-button nibi-button--link clamp-toggle" aria-expanded={expanded} aria-controls={textId} onClick={() => setExpanded((value) => !value)}>
            {expanded ? "たたむ" : "全文を表示"}
          </button>
        </p>
      )}
    </>
  );
}
