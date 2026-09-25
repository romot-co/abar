import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type CSSProperties } from "react";
import { api, type Action, type Project, type SessionCompletion } from "../api";
import { humanError } from "../errors";
import type { RelistenItemView, SessionResultView } from "../generated";
import { Mark, type MarkKind } from "../Mark";
import { activeCells, answerWords, gaugeEnds, identityLabel, orientAnswer, type GaugeEnds } from "./gauge";
import { conditionReason } from "./resultCopy";
import { InlineError } from "../InlineError";

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

  const headingRef = useRef<HTMLHeadingElement>(null);
  const loaded = completion.data !== undefined;
  // 回答ボタンが消えた後のフォーカスをbodyへ落とさず、結果の見出しへ移す。
  useEffect(() => { if (loaded) headingRef.current?.focus({ preventScroll: true }); }, [loaded]);

  if (completion.isPending) return <main className="centered">結果をまとめています…</main>;
  if (completion.isError || !completion.data) return <main className="centered error-panel"><h1>結果を表示できません</h1><p>{completion.error ? humanError(completion.error) : null}</p><div className="centered-actions"><button type="button" className="nibi-button secondary-action" onClick={onBack}>受信箱へ</button></div></main>;

  const data = completion.data;
  const result = data.result;
  const readyCount = project.data?.sessions.filter((item) => item.status === "ready").length ?? 0;
  const verdict = verdictCopy(data);
  const kind = data.current_best_check ? "最良の更新" : result ? "観察" : "試聴";
  // この画面は終了したSessionだけを表示する(§7.9: A/Bと候補の対応はここで公開できる)。ゲージは候補の向きに固定する。
  const ends = gaugeEnds(result, data.items);

  return (
    <div className="docked-screen summary-page">
      <main className="screen summary-shell">
        <div className="summary-heading">
          <p className="nibi-label result-eyebrow">
            {kind} · 全 {data.comparison_count} 比較{data.recipe ? <> · <span>{`Recipe ${data.recipe}`}</span></> : ""}
          </p>
          <h1 ref={headingRef} tabIndex={-1} className="nibi-title">{data.focus ?? "比較の結果"}</h1>
        </div>

        <section className={result?.current_best_updated ? "nibi-card nibi-card--lead verdict-card updated" : "nibi-card nibi-card--lead verdict-card"} aria-labelledby="verdict-title">
          <strong id="verdict-title" className="nibi-title">{verdict.title}</strong>
          {verdict.detail && <p className="nibi-body verdict-detail">{verdict.detail}</p>}
          {result && <Tally result={result} ends={ends} />}
          {result && (
            <ul className="verdict-reasons" aria-label="根拠">
              {reasons(data, result).map((reason) => (
                <li key={reason.text} className="nibi-body"><Mark kind={reason.kind} /><span className={reason.kind === "fail" ? "reason-fail" : undefined}>{reason.text}</span></li>
              ))}
            </ul>
          )}
          {readyNext && <p className="nibi-body verdict-next">次の未回答:「{readyNext.focus}」</p>}
        </section>

        <section className="answer-section" aria-labelledby="answer-record-heading">
          <h2 id="answer-record-heading" className="nibi-heading">回答 · 全 {data.items.length} 比較</h2>
          <GaugeLegend ends={ends} />
          <div
            className="nibi-rowlist nibi-rowlist--faced nibi-rowlist--striped nibi-rowlist--start nibi-rowlist--stack nibi-rowlist--stack-3 answer-record"
            role="table"
            aria-label="回答"
            style={{ "--nibi-rowlist-cols": "1.5rem auto minmax(0, 1fr)", "--nibi-rowlist-cols-narrow": "1.5rem auto minmax(0, 1fr)" } as CSSProperties}
          >
            <div className="nibi-rowlist__head" role="row">
              <span role="columnheader">#</span>
              <span role="columnheader" className="gauge-head">向き</span>
              <span role="columnheader">判定</span>
            </div>
            {data.items.map((item) => <AnswerRow key={item.delivery_id} item={item} result={result} ends={ends} />)}
          </div>
        </section>
        {start.isError && <InlineError>{humanError(start.error)}</InlineError>}
      </main>
      <div className="nibi-dock summary-actions">
        {readyNext && (
          <button type="button" className="nibi-button nibi-button--primary primary-action" disabled={start.isPending} onClick={() => start.mutate(readyNext.project_session_id)}>
            次へ（残り {readyCount}）
          </button>
        )}
        <p className="summary-back">
          <button type="button" className="nibi-button nibi-button--link weak-action" onClick={onBack}>受信箱へ</button>
        </p>
      </div>
    </div>
  );
}

/* ゲージの両端の名前。狭い列でも省かない(折り返す)。 */
function GaugeLegend({ ends }: { ends: GaugeEnds }) {
  return (
    <p className="gauge-legend nibi-label" aria-label={`ゲージの向き: 左 ${endWords(ends.left)}、右 ${endWords(ends.right)}`}>
      <span className="gauge-end start" aria-hidden="true">
        <span className="gauge-end-name">{ends.left.label}</span>
        {ends.left.role && <span className="gauge-end-role">{ends.left.role}</span>}
      </span>
      <span className="answer-gauge" aria-hidden="true">{[1, 2, 3, 4, 5].map((value) => <span key={value} />)}</span>
      <span className="gauge-end end" aria-hidden="true">
        <span className="gauge-end-name">{ends.right.label}</span>
        {ends.right.role && <span className="gauge-end-role">{ends.right.role}</span>}
      </span>
    </p>
  );
}

function endWords(end: GaugeEnds["left"]): string {
  return end.role ? `${end.label}（${end.role}）` : end.label;
}

/* 支持の数: ゲージと同じ並び(左の候補 · 互角 · 右の候補)。Plan付きでは現在最良と提案を名前の下に言う。 */
function Tally({ result, ends }: { result: SessionResultView; ends: GaugeEnds }) {
  const side = (end: GaugeEnds["left"]) => ({
    key: end.key,
    label: end.label,
    role: end.role,
    value: result.evidence_direction_counts[end.key] ?? 0,
    strong: end.key === result.favored_variant_id,
  });
  const entries = ends.bySlot
    ? Object.entries(result.variant_labels).map(([key, label]) => side({ key, label, role: null }))
    : [side(ends.left), { key: "tie", label: "互角", role: null, value: result.evidence_direction_counts.tie ?? 0, strong: false }, side(ends.right)];
  if (ends.bySlot) entries.push({ key: "tie", label: "互角", role: null, value: result.evidence_direction_counts.tie ?? 0, strong: false });
  const answered = Object.values(result.evidence_direction_counts).reduce((total, count) => total + count, 0);
  if (answered < result.evidence_count) entries.push({ key: "missing", label: "未回答", role: null, value: result.evidence_count - answered, strong: false });
  return (
    <div className="verdict-tally" aria-label="支持の数">
      {entries.map((entry) => (
        <span key={entry.key} className="tally-item">
          <span className={entry.strong ? "nibi-display tally-value strong" : "nibi-display tally-value"}>{entry.value}</span>
          <span className="nibi-label tally-label">{entry.label}</span>
          {entry.role && <span className="nibi-label tally-role">{entry.role}</span>}
        </span>
      ))}
    </div>
  );
}

function AnswerRow({ item, result, ends }: { item: RelistenItemView; result: SessionResultView | null; ends: GaugeEnds }) {
  const preference = item.skipped ? null : item.judgment?.preference ?? null;
  const note = answerNote(item);
  const judgment = rowJudgment(item, preference, result);
  const muted = preference === null || preference === 3;
  const oriented = orientAnswer(item, ends, preference);
  const active = activeCells(oriented);
  return (
    <div className="nibi-rowlist__row answer-table-row" role="row">
      <span role="rowheader" className="nibi-value answer-index">{item.sequence_index + 1}</span>
      <span role="cell" className="answer-gauge" data-orientation={oriented.kind} aria-label={answerWords(oriented, ends)}>
        {[0, 1, 2, 3, 4].map((cell) => <span key={cell} className={active.includes(cell) ? "active" : ""} />)}
      </span>
      <span role="cell" className="nibi-rowlist__title nibi-rowlist__title--plain nibi-body answer-main">
        <span className={muted ? "nibi-rowlist__name answer-judgment neutral" : "nibi-rowlist__name answer-judgment"}>{judgment}</span>
        <span className="nibi-rowlist__sub result-pair" title={item.clip_id ?? undefined}>
          <span className={`result-role ${item.role}`}>{roleLabel(item.role)}</span>
          {item.material_name && <span> · {item.material_name}</span>}
          {item.role === "evidence" && <> · <strong>A</strong> <span>{slotLabel(item, "A")}</span> · <strong>B</strong> <span>{slotLabel(item, "B")}</span></>}
        </span>
        {note && <span className="nibi-rowlist__sub answer-note">{note}</span>}
      </span>
    </div>
  );
}

function normalizedPreferenceText(item: RelistenItemView, preference: 1 | 2 | 3 | 4 | 5): string {
  if (preference === 3) return "互角";
  const slot = preference < 3 ? "A" : "B";
  const strength = preference === 1 || preference === 5 ? "明確に" : "わずかに";
  return `${slotLabel(item, slot)}を${strength}支持`;
}

function rowJudgment(
  item: RelistenItemView,
  preference: 1 | 2 | 3 | 4 | 5 | null,
  result: SessionResultView | null,
): string {
  if (preference === null) {
    const missing = item.skipped ? "飛ばした" : "未回答";
    if (item.role === "same") return `同一音: ${missing}`;
    if (item.role === "repeat") return `再現性: ${missing}`;
    return item.skipped ? "飛ばした" : "回答なし";
  }
  if (item.role === "same") {
    const strength = preference === 1 || preference === 5 ? "明確" : "わずか";
    return result?.same_result === "tie" ? "同一音: 一致" : `同一音: 差を報告（${strength}）`;
  }
  if (item.role === "repeat") {
    const current = normalizedPreferenceText(item, preference);
    return `再現性: ${repeatResultLabel(result?.repeat_result)}（今回: ${current}）`;
  }
  return normalizedPreferenceText(item, preference);
}

function answerNote(item: RelistenItemView): string {
  if (item.skipped || !item.judgment) return "";
  const notes: string[] = [];
  for (const slot of ["a", "b"] as const) {
    const blocker = item.judgment.blockers[slot];
    if (!blocker?.selected) continue;
    const name = slotLabel(item, slot === "a" ? "A" : "B");
    notes.push(`${name}に問題${blocker.note ? `（${blocker.note}）` : ""}`);
  }
  if (item.judgment.comment) notes.push(item.judgment.comment);
  return notes.join(" · ");
}

function verdictCopy(data: SessionCompletion): { title: string; detail: string } {
  const result = data.result;
  if (!result) return { title: "比較を記録しました", detail: "この試聴はProjectに属さないため、現在最良は変わりません。" };
  if (data.current_best_check) {
    if (result.current_best_updated) return { title: `現在最良を ${result.favored_variant_label ?? "提案版"} に更新`, detail: "" };
    return { title: "現在最良を維持", detail: keepReason(result) ?? "" };
  }
  const directional = Object.keys(result.variant_labels).map((variantId) => result.evidence_direction_counts[variantId] ?? 0);
  const tieCount = result.evidence_direction_counts.tie ?? 0;
  let conclusion: string;
  if (result.favored_variant_label) conclusion = `${result.favored_variant_label} が優勢`;
  else if (tieCount === result.evidence_count) conclusion = "全比較で互角";
  else if (directional.every((count) => count === 0)) conclusion = "判定できる回答が不足しています";
  else if (directional.length === 2 && directional[0] === directional[1]) conclusion = "判断が素材によって分かれました";
  else conclusion = "支持が多い方向はありますが、優勢条件には届きませんでした";
  return { title: conclusion, detail: "観察として記録しました（現在最良は変わりません）" };
}

// 更新しなかった理由を、サーバーの判定順(未回答 → blocker → 優勢条件)に合わせて一つだけ示す。
function keepReason(result: SessionResultView): string | null {
  const evidence = result.best_update_evidence;
  if (!evidence) return null;
  if (evidence.answered_count < evidence.evidence_count) return "飛ばした比較があるため、更新条件を満たしませんでした";
  if (evidence.blocker_count > 0) return "提案版に残せない問題が報告されたため、更新しませんでした";
  if (evidence.favorable_count < result.favored_required_count) {
    return `提案版を支持した比較は${evidence.evidence_count}件中${evidence.favorable_count}件で、必要な${result.favored_required_count}件に届きませんでした`;
  }
  if (evidence.score_sum <= 0) return "提案版への支持が反対の回答を上回らず、優勢条件を満たしませんでした";
  return null;
}

// 根拠の行: 優勢条件 / 同一音の確認 / 再現性の確認。1つでも不合格なら、どこで止まったかがここで読める。
function reasons(data: SessionCompletion, result: SessionResultView): Array<{ kind: MarkKind; text: string }> {
  // 条件に届かないこと・問題の報告は現在最良を維持する普通の理由なので、失敗(fail)の印にしない。
  const rows: Array<{ kind: MarkKind; text: string }> = [conditionReason(result)];
  const evidence = result.best_update_evidence;
  if (evidence && evidence.blocker_count > 0) rows.push({ kind: "unknown", text: "提案に残せない問題の報告あり" });
  if (data.items.some((item) => item.role === "same")) {
    const kind: MarkKind = result.same_result === "tie" ? "pass" : result.same_result === "difference_reported" ? "fail" : "unknown";
    rows.push({ kind, text: `同一音の確認: ${sameResultLabel(result.same_result)}` });
  }
  if (data.items.some((item) => item.role === "repeat")) {
    const value = result.repeat_result;
    const kind: MarkKind = value === "same_category" || value === "same_direction" ? "pass" : value === "reversed" ? "fail" : "unknown";
    rows.push({ kind, text: `再現性の確認: ${repeatResultLabel(value)}` });
  }
  return rows;
}

function sameResultLabel(value: string | undefined): string {
  return { tie: "一致", difference_reported: "差を報告", missing: "未回答" }[value ?? "missing"] ?? value ?? "未回答";
}

function repeatResultLabel(value: string | undefined): string {
  return {
    same_category: "同一強度",
    same_direction: "同方向",
    near: "片方tie",
    reversed: "反転",
    missing: "未回答",
  }[value ?? "missing"] ?? value ?? "未回答";
}

function roleLabel(role: RelistenItemView["role"]): string {
  return { evidence: "素材", same: "同一音の確認", repeat: "再現性の確認", other: "比較" }[role];
}

function slotLabel(item: RelistenItemView, slot: "A" | "B"): string {
  if (item.role === "same") return "同一音";
  return identityLabel(item.identity_by_slot[slot]);
}
