import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Action, type Project, type SessionCompletion } from "../api";
import { humanError } from "../errors";
import type { RelistenItemView, SessionResultView } from "../generated";

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

  if (completion.isPending) return <main className="centered">結果をまとめています…</main>;
  if (completion.isError || !completion.data) return <main className="centered error-panel"><h1>結果を表示できません</h1><p>{completion.error ? humanError(completion.error) : null}</p><button type="button" className="secondary-action" onClick={onBack}>受信箱へ</button></main>;

  const data = completion.data;
  const result = data.result;
  const readyCount = project.data?.sessions.filter((item) => item.status === "ready").length ?? 0;
  const verdict = verdictCopy(data);

  return (
    <main className="summary-shell">
      <p className="result-eyebrow">
        {data.current_best_check ? "現在最良チェック" : "観察"} · 全{data.comparison_count}比較
        {data.recipe ? <> · <span>{`Recipe ${data.recipe}`}</span></> : ""}
      </p>
      <h1>{data.focus ?? "比較の結果"}</h1>

      <section className={result?.current_best_updated ? "verdict-card updated" : "verdict-card"}>
        <strong>{verdict.title}</strong>
        {verdict.detail ? <p>{verdict.detail}</p> : null}
      </section>

      <section className="answer-record" aria-label="回答の記録">
        <div className="answer-table-head">
          <span>#</span>
          <span>比較</span>
          <span>判定</span>
          <span>メモ</span>
        </div>
        {data.items.map((item) => <AnswerRow key={item.delivery_id} item={item} result={result} />)}
      </section>

      <div className="summary-actions">
        <button type="button" className="secondary-action" onClick={onBack}>受信箱へ</button>
        {readyNext && (
          <button type="button" className="primary-action" disabled={start.isPending} onClick={() => start.mutate(readyNext.project_session_id)}>
            次を聴く（残り {readyCount}）
          </button>
        )}
      </div>
      {start.isError && <p className="inline-error">{humanError(start.error)}</p>}
    </main>
  );
}

function AnswerRow({ item, result }: { item: RelistenItemView; result: SessionResultView | null }) {
  const preference = item.skipped ? null : item.judgment?.preference ?? null;
  const note = answerNote(item);
  const judgment = rowJudgment(item, preference, result);
  const displayedJudgment = item.skipped && !["same", "repeat"].includes(item.role) ? "skip" : judgment;
  return (
    <div className="answer-table-row">
      <span>{item.sequence_index + 1}</span>
      <span className="result-pair" title={item.clip_id ?? undefined}>
        <span className={`result-role ${item.role}`}>{roleLabel(item.role)}</span>
        <span><strong>A</strong> <span>{slotLabel(item, "A")}</span></span>
        <span><strong>B</strong> <span>{slotLabel(item, "B")}</span></span>
        {item.material_name && <small>{item.material_name}</small>}
      </span>
      <span className="result-judgment">
        <span className="answer-gauge" aria-label={judgment}>
          {([1, 2, 3, 4, 5] as const).map((value) => <span key={value} className={preference === value ? "active" : ""} />)}
        </span>
        <strong className={preference === 3 ? "answer-judgment neutral" : "answer-judgment"}>{displayedJudgment}</strong>
      </span>
      <span className="answer-note" title={note}>{note}</span>
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
    if (item.role === "same") return "同一音: 未回答";
    if (item.role === "repeat") return "再現性: 未回答";
    return "回答なし";
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
  if (item.skipped) return "skip";
  if (!item.judgment) return "";
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
  if (!result) return { title: "比較を記録しました", detail: "結果はProject Sessionへ記録されていません。" };
  const detail = `${resultBreakdown(result)}${qcBreakdown(result, data.items)}`;
  if (data.current_best_check) {
    return result.current_best_updated
      ? { title: `現在最良を ${result.favored_variant_label ?? "提案版"} に更新しました`, detail }
      : { title: "現在最良を維持します", detail };
  }
  const directional = Object.keys(result.variant_labels).map((variantId) => result.evidence_direction_counts[variantId] ?? 0);
  const tieCount = result.evidence_direction_counts.tie ?? 0;
  let conclusion: string;
  if (result.favored_variant_label) conclusion = `${result.favored_variant_label} が優勢`;
  else if (tieCount === result.evidence_count) conclusion = "全比較で互角";
  else if (directional.every((count) => count === 0)) conclusion = "判定できる回答が不足しています";
  else if (directional.length === 2 && directional[0] === directional[1]) conclusion = "判断が素材によって分かれました";
  else conclusion = "支持が多い方向はありますが、優勢条件には届きませんでした";
  return {
    title: "観察として記録しました（現在最良は変わりません）",
    detail: `${conclusion} · ${detail}`,
  };
}

function resultBreakdown(result: SessionResultView): string {
  const counts = Object.entries(result.variant_labels).map(([variantId, label]) => `${label} ${result.evidence_direction_counts[variantId] ?? 0}`);
  counts.push(`互角 ${result.evidence_direction_counts.tie ?? 0}`);
  const answered = Object.values(result.evidence_direction_counts).reduce((total, count) => total + count, 0);
  if (answered < result.evidence_count) counts.push(`未回答 ${result.evidence_count - answered}`);
  return `${counts.join(" / ")}（優勢条件 ${result.favored_required_count}/${result.evidence_count}）`;
}

function qcBreakdown(result: SessionResultView, items: RelistenItemView[]): string {
  const checks: string[] = [];
  if (items.some((item) => item.role === "same")) checks.push(`同一音: ${sameResultLabel(result.same_result)}`);
  if (items.some((item) => item.role === "repeat")) checks.push(`再現性: ${repeatResultLabel(result.repeat_result)}`);
  return checks.length > 0 ? ` · QC ${checks.join(" / ")}` : "";
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
  return { evidence: "素材", same: "同一音チェック", repeat: "再現性チェック", other: "比較" }[role];
}

function slotLabel(item: RelistenItemView, slot: "A" | "B"): string {
  if (item.role === "same") return "同一音";
  return identityLabel(item.identity_by_slot[slot]);
}

function identityLabel(value: Record<string, unknown> | undefined): string {
  if (!value) return "unknown";
  if (typeof value.label === "string") return value.label;
  const provenance = value.provenance;
  if (provenance && typeof provenance === "object") {
    const record = provenance as Record<string, unknown>;
    return String(record.variant_ref ?? record.name ?? record.audio_id ?? value.audio_id ?? "audio");
  }
  return String(value.audio_id ?? "audio");
}
