import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, type Action, type Project, type SessionCompletion } from "../api";
import { ClampedText } from "../ClampedText";
import { humanError } from "../errors";
import type { RelistenItemView, SessionResultView } from "../generated";
import { Icon } from "../Icon";
import { Mark, type MarkKind } from "../Mark";
import { axisNames, shortenPair, type CandidateName } from "./candidateNames";
import { answerWords, gaugeEnds, identityKey, orientAnswer, rowGauge, supportChart, type GaugeEnds, type OrientedAnswer, type Preference, type RowGauge, type SupportChart } from "./gauge";
import { conclusion } from "./resultCopy";
import { InlineError } from "../InlineError";

/*
 * 結果(§8.3): 終了したSessionだけを表示する(§7.9: A/Bと候補の対応はここで初めて公開できる)。
 * 上段(受信箱へ · 種類と比較数)→ 結論(見出しと支える文1つ)→ 集計の面(左右の軸、件数、支持の図、候補の正式名)
 * → 問い → 回答(比較ごとのゲージとコメント)→ 回答の確かさ(同一音・再現性の確認)。下に固定した操作欄に「次へ」。
 */
export function SessionSummary({ sessionId, onBack, onNext }: { sessionId: string; onBack: () => void; onNext?: () => void }) {
  const queryClient = useQueryClient();
  const completion = useQuery({
    queryKey: ["completion", sessionId],
    queryFn: () => api<SessionCompletion>(`/api/sessions/${sessionId}/completion`),
  });
  const project = useQuery({
    queryKey: ["project", "completion"],
    queryFn: () => api<Project>("/api/project"),
    enabled: onNext !== undefined,
  });
  const readyNext = onNext
    ? project.data?.sessions.find((item) => item.status === "ready") ?? null
    : null;
  const start = useMutation({
    mutationFn: (coreSessionId: string) =>
      api<Action>(`/api/sessions/${coreSessionId}/start`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
      onNext?.();
    },
  });
  const [showSlots, setShowSlots] = useState(false);

  const headingRef = useRef<HTMLHeadingElement>(null);
  const loaded = completion.data !== undefined;
  // 回答ボタンが消えた後のフォーカスをbodyへ落とさず、結果の見出しへ移す。
  useEffect(() => { if (loaded) headingRef.current?.focus({ preventScroll: true }); }, [loaded]);

  if (completion.isPending) return <main className="centered">結果をまとめています…</main>;
  if (completion.isError || !completion.data) return <main className="centered error-panel"><h1>結果を表示できません</h1><p>{completion.error ? humanError(completion.error) : null}</p><div className="centered-actions"><button type="button" className="nibi-button secondary-action" onClick={onBack}>受信箱へ</button></div></main>;

  const data = completion.data;
  const result = data.result;
  const readyCount = project.data?.sessions.filter((item) => item.status === "ready").length ?? 0;
  const kind = data.current_best_check ? "最良の更新" : result ? "観察" : "試聴";
  // ゲージは候補の向きに固定する(左 = 開始時の現在最良 / 組の1つ目、右 = 提案 / 2つ目)。
  const ends = gaugeEnds(result, data.items);
  const [leftName, rightName] = shortenPair(ends.left.label, ends.right.label);
  const axis = ends.bySlot ? { left: "A", right: "B", aliased: false } : axisNames(leftName, rightName, data.current_best_check);
  const proposedName = [...rightName.short].length <= 12 ? rightName.short : null;
  const verdict = conclusion(result, ends, axis, proposedName);
  const axisEnds: GaugeEnds = { ...ends, left: { ...ends.left, label: axis.left }, right: { ...ends.right, label: axis.right } };
  const answers = data.items.filter((item) => item.role !== "same" && item.role !== "repeat");
  const checks = data.items.filter((item) => item.role === "same" || item.role === "repeat");
  const oriented = answers.map((item) => orientAnswer(item, ends, preferenceOf(item)));

  return (
    <div className="docked-screen summary-page">
      <main className="screen summary-shell">
        <div className="summary-lead">
          <div className="summary-top">
            <button type="button" className="nibi-button nibi-button--link weak-action" onClick={onBack}>受信箱へ</button>
            <span className="nibi-body summary-kind">{kind} · {data.comparison_count} 比較</span>
          </div>
          <header className="summary-conclusion">
            <h1 ref={headingRef} tabIndex={-1} id="verdict-title" className="nibi-display verdict-title">{verdict.headline}</h1>
            {verdict.detail && <p className="nibi-body verdict-detail">{verdict.detail}</p>}
          </header>
        </div>

        {result && (
          <section className="nibi-panel tally-panel" aria-label="支持の数">
            <Tally result={result} ends={ends} axis={axis} names={[leftName, rightName]} plan={data.current_best_check} />
            <SupportChartView chart={supportChart(oriented.filter((_, index) => answers[index]?.role === "evidence"), result.favored_required_count, result.evidence_count)} />
            {!ends.bySlot && <NamesDisclosure names={[leftName, rightName]} />}
          </section>
        )}

        {data.focus && (
          <section className="summary-section question-section" aria-labelledby="question-heading">
            <h2 id="question-heading" className="nibi-heading">問い</h2>
            <div className="summary-question">
              <ClampedText className="nibi-body result-question">{data.focus}</ClampedText>
            </div>
          </section>
        )}

        <section className="summary-section answer-section" aria-labelledby="answer-record-heading">
          <div className="section-head">
            <h2 id="answer-record-heading" className="nibi-heading">回答<span className="heading-count"> {answers.length} 比較</span></h2>
            {!ends.bySlot && answers.length > 0 && (
              <button type="button" className="nibi-button nibi-button--link weak-action slots-toggle" aria-pressed={showSlots} onClick={() => setShowSlots((value) => !value)}>
                {showSlots ? "A/B の割り当てを隠す" : "A/B の割り当てを表示"}
              </button>
            )}
          </div>
          <div
            className="nibi-rowlist nibi-rowlist--prose nibi-rowlist--ruled nibi-rowlist--start answer-list"
            role="table"
            aria-label="回答"
          >
            <div className="nibi-rowlist__head" role="row">
              <span role="columnheader" className="answer-head-index">#</span>
              <span role="columnheader" className="answer-head-material">素材</span>
              <span role="columnheader" className="gauge-head" aria-label={`向き: 左 ${axis.left}、右 ${axis.right}`}>
                <span className="gauge-head-end start" aria-hidden="true">← {axis.left}</span>
                <span className="gauge-head-end end" aria-hidden="true">{axis.right} →</span>
              </span>
              <span role="columnheader" className="answer-head-comment">コメント</span>
            </div>
            {answers.map((item, index) => (
              <AnswerRow key={item.delivery_id} item={item} ends={axisEnds} oriented={oriented[index] ?? { kind: "missing" }} showSlots={showSlots} />
            ))}
          </div>
        </section>

        {checks.length > 0 && (
          <section className="summary-section checks-section" aria-labelledby="checks-heading">
            <h2 id="checks-heading" className="nibi-heading">回答の確かさ</h2>
            <ul className="nibi-rowlist nibi-rowlist--bare nibi-rowlist--prose nibi-rowlist--ruled check-list" aria-label="回答の確かさ" style={{ "--nibi-rowlist-cols": "minmax(0, 1fr) auto" } as CSSProperties}>
              {checks.map((item) => {
                const check = checkResult(item, result);
                return (
                  <li key={item.delivery_id} className="nibi-rowlist__row check-row">
                    <span className="nibi-rowlist__title nibi-rowlist__title--plain nibi-body">
                      <span className="nibi-rowlist__name check-name">{item.role === "same" ? "同一音の確認" : "再現性の確認"}</span>
                      {item.material_name && <span className="check-material">{item.material_name}</span>}
                    </span>
                    <span className={`nibi-rowlist__status nibi-body check-status ${check.kind}`}><Mark kind={check.kind} />{check.words}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {start.isError && <InlineError>{humanError(start.error)}</InlineError>}
      </main>
      {readyNext && (
        <div className="nibi-dock screen-dock summary-dock">
          <div className="screen-dock__inner">
            <span className="nibi-body next-focus" title={readyNext.focus}>次: {readyNext.focus}</span>
            <button type="button" className="nibi-button nibi-button--primary primary-action next-action" disabled={start.isPending} onClick={() => start.mutate(readyNext.project_session_id)}>
              次へ（残り {readyCount}）
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function preferenceOf(item: RelistenItemView): Preference | null {
  return item.skipped ? null : item.judgment?.preference ?? null;
}

/* 集計: 左右の軸の名前(短縮名、2行まで)、役割か「候補 1 / 2」、件数、互角と未回答。 */
function Tally({ result, ends, axis, names, plan }: { result: SessionResultView; ends: GaugeEnds; axis: { left: string; right: string; aliased: boolean }; names: [CandidateName, CandidateName]; plan: boolean }) {
  const count = (key: string) => result.evidence_direction_counts[key] ?? 0;
  const ties = result.evidence_direction_counts.tie ?? 0;
  const answered = Object.values(result.evidence_direction_counts).reduce((total, value) => total + value, 0);
  const missing = Math.max(0, result.evidence_count - answered);
  const roles = plan || axis.aliased;
  const favored = result.favored_variant_id;
  return (
    <div className="tally-grid">
      <span className="nibi-body tally-name start" title={names[0].full}>← {ends.bySlot ? axis.left : names[0].short}</span>
      <span />
      <span className="nibi-body tally-name end" title={names[1].full}>{ends.bySlot ? axis.right : names[1].short} →</span>
      {roles && (
        <>
          <span className="nibi-body tally-role start">{plan ? ends.left.role ?? axis.left : axis.left}</span>
          <span />
          <span className="nibi-body tally-role end">{plan ? ends.right.role ?? axis.right : axis.right}</span>
        </>
      )}
      <span className={favored === ends.left.key ? "nibi-display tally-count start favored" : "nibi-display tally-count start"} aria-label={`${axis.left} ${count(ends.left.key)} 件`}>{count(ends.left.key)}</span>
      <span className="tally-middle">
        <span className="nibi-body">互角 {ties}</span>
        {missing > 0 && <span className="nibi-body">未回答 {missing}</span>}
      </span>
      <span className={favored === ends.right.key ? "nibi-display tally-count end favored" : "nibi-display tally-count end"} aria-label={`${axis.right} ${count(ends.right.key)} 件`}>{count(ends.right.key)}</span>
    </div>
  );
}

/* 支持の図(handoff 3.1)。読み上げの対象から外す(同じ内容は集計と結論の文で伝える)。 */
function SupportChartView({ chart }: { chart: SupportChart }) {
  const style = { "--slots": chart.slots, "--tick-left": chart.tickLeft, "--tick-right": chart.tickRight } as CSSProperties;
  return (
    <div className="support-chart" aria-hidden="true" style={style}>
      <span className="support-chart__rail" />
      <span className="support-chart__half start">
        {chart.left.map((strength, index) => <span key={index} className="support-chart__block" data-strength={strength} />)}
      </span>
      <span className="support-chart__half end">
        {chart.right.map((strength, index) => <span key={index} className="support-chart__block" data-strength={strength} />)}
      </span>
      <span className="support-chart__center" />
      <span className="support-chart__tick start" />
      <span className="support-chart__tick end" />
    </div>
  );
}

function NamesDisclosure({ names }: { names: [CandidateName, CandidateName] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="nibi-disclosure nibi-disclosure--link names-disclosure">
      <button type="button" className="nibi-disclosure__header" aria-expanded={open} aria-controls="candidate-names" onClick={() => setOpen((value) => !value)}>
        <Icon name="chevron_right" className="nibi-disclosure__chevron" />候補の正式名
      </button>
      <div id="candidate-names" className="nibi-disclosure__region" hidden={!open}>
        <div className="candidate-names">
          {names.map((name, index) => (
            <p key={index} className="nibi-body candidate-name">
              <span className="candidate-side" aria-label={index === 0 ? "左" : "右"}>{index === 0 ? "←" : "→"}</span>
              <span className="candidate-full">
                {name.tokens.map((token, tokenIndex) => (
                  <span key={tokenIndex} className={token.differs ? "candidate-token differs" : "candidate-token"}>{tokenIndex > 0 ? " " : ""}{token.text}</span>
                ))}
              </span>
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

function AnswerRow({ item, ends, oriented, showSlots }: { item: RelistenItemView; ends: GaugeEnds; oriented: OrientedAnswer; showSlots: boolean }) {
  const gauge = rowGauge(oriented, item.skipped);
  const note = answerNote(item, ends);
  const words = oriented.kind === "missing" ? gauge.word : answerWords(oriented, ends);
  return (
    <div className="nibi-rowlist__row answer-row" role="row">
      <span role="rowheader" className="nibi-rowlist__num nibi-value answer-index">{item.sequence_index + 1}</span>
      <span role="cell" className="nibi-body answer-material" title={item.clip_id ?? undefined}>{item.material_name ?? "—"}</span>
      <span role="cell" className="answer-gauge-cell">
        <RowGaugeView gauge={gauge} label={words} />
        {showSlots && <span className="nibi-label answer-slots">{slotWords(item, ends)}</span>}
      </span>
      <span role="cell" className={note ? "nibi-body answer-comment" : "nibi-body answer-comment empty"}>{note || "—"}</span>
    </div>
  );
}

/* 比較ごとのゲージ(handoff 3.2)。図の下に言葉を必ず添える。読み上げは「Depth 60 をわずかに支持」のような一文。 */
function RowGaugeView({ gauge, label }: { gauge: RowGauge; label: string }) {
  return (
    <span className="row-gauge" role="img" aria-label={label} data-side={gauge.side ?? "none"}>
      <span className="row-gauge__track" aria-hidden="true">
        <span className="row-gauge__rail" />
        <span className="row-gauge__half start">
          {gauge.side === "left" && gauge.blocks.map((strength, index) => <span key={index} className="row-gauge__block" data-strength={strength} />)}
        </span>
        <span className="row-gauge__half end">
          {gauge.side === "right" && gauge.blocks.map((strength, index) => <span key={index} className="row-gauge__block" data-strength={strength} />)}
        </span>
        <span className="row-gauge__center" />
        {gauge.side === "center" && <span className="row-gauge__dot" />}
      </span>
      <span className="nibi-label row-gauge__word" aria-hidden="true">{gauge.word}</span>
    </span>
  );
}

// A/B の割り当て(終了後だけ、既定は隠す)。A と B がそれぞれどちらの軸だったか。
function slotWords(item: RelistenItemView, ends: GaugeEnds): string {
  if (ends.bySlot) return "";
  const side = (slot: "A" | "B") => {
    const key = identityKey(item.identity_by_slot[slot]);
    return key === ends.left.key ? ends.left.label : key === ends.right.key ? ends.right.label : "—";
  };
  return `A = ${side("A")} · B = ${side("B")}`;
}

function answerNote(item: RelistenItemView, ends: GaugeEnds): string {
  if (item.skipped || !item.judgment) return "";
  const notes: string[] = [];
  for (const slot of ["a", "b"] as const) {
    const blocker = item.judgment.blockers[slot];
    if (!blocker?.selected) continue;
    const upper = slot === "a" ? "A" : "B";
    const key = identityKey(item.identity_by_slot[upper]);
    const name = ends.bySlot ? upper : key === ends.left.key ? ends.left.label : key === ends.right.key ? ends.right.label : upper;
    notes.push(`${name} に問題${blocker.note ? `（${blocker.note}）` : ""}`);
  }
  if (item.judgment.comment) notes.push(item.judgment.comment);
  return notes.join(" · ");
}

function checkResult(item: RelistenItemView, result: SessionResultView | null): { kind: MarkKind; words: string } {
  const preference = preferenceOf(item);
  if (preference === null) return { kind: "unknown", words: item.skipped ? "飛ばした" : "未回答" };
  if (item.role === "same") {
    if (preference === 3) return { kind: "pass", words: "一致" };
    return { kind: "fail", words: `差を報告（${preference === 1 || preference === 5 ? "明確" : "わずか"}）` };
  }
  const value = result?.repeat_result;
  const kind: MarkKind = value === "same_category" || value === "same_direction" ? "pass" : value === "reversed" ? "fail" : "unknown";
  return { kind, words: repeatResultLabel(value) };
}

function repeatResultLabel(value: string | undefined): string {
  return {
    same_category: "同じ強さで一致",
    same_direction: "同じ向き",
    near: "片方が互角",
    reversed: "反転",
    missing: "未回答",
  }[value ?? "missing"] ?? value ?? "未回答";
}
