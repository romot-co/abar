import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Action, type Project, type SessionCompletion } from "../api";
import { humanError } from "../errors";
import type { RelistenItemView } from "../generated";

export function SessionSummary({ sessionId, onBack, onNext }: { sessionId: string; onBack: () => void; onNext: () => void }) {
  const queryClient = useQueryClient();
  const completion = useQuery({
    queryKey: ["completion", sessionId],
    queryFn: () => api<SessionCompletion>(`/api/sessions/${sessionId}/completion`),
  });
  const project = useQuery({
    queryKey: ["project", "completion"],
    queryFn: () => api<Project>("/api/project"),
  });
  const readyNext = project.data?.sessions.find((item) => item.status === "ready") ?? null;
  const start = useMutation({
    mutationFn: (coreSessionId: string) =>
      api<Action>(`/api/sessions/${coreSessionId}/start`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
      onNext();
    },
  });

  if (completion.isPending) return <main className="centered">結果をまとめています…</main>;
  if (completion.isError || !completion.data) return <main className="centered error-panel"><h1>結果を表示できません</h1><p>{completion.error ? humanError(completion.error) : null}</p><button type="button" className="secondary-action" onClick={onBack}>受信箱へ</button></main>;

  const data = completion.data;
  const result = data.result;
  const identity = data.items[0]?.identity_by_slot ?? null;
  const readyCount = project.data?.sessions.filter((item) => item.status === "ready").length ?? 0;
  const verdict = verdictCopy(data);

  return (
    <main className="summary-shell">
      <p className="result-eyebrow">{data.current_best_check ? "現在最良チェック" : "観察"} · 全{data.comparison_count}比較</p>
      <h1>{data.focus ?? "比較の結果"}</h1>

      <section className={result?.current_best_updated ? "verdict-card updated" : "verdict-card"}>
        <strong>{verdict.title}</strong>
        {verdict.detail ? <p>{verdict.detail}</p> : null}
      </section>

      <section className="answer-record" aria-label="回答の記録">
        {identity && (
          <p className="result-identity">
            {(["A", "B"] as const).map((slot) => (
              <span key={slot}><strong>{slot}</strong> = <code>{identityLabel(identity[slot])}</code></span>
            ))}
          </p>
        )}
        <div className="answer-table-head">
          <span>#</span>
          <span>A ← → B</span>
          <span>判定</span>
          <span>メモ</span>
        </div>
        {data.items.map((item) => <AnswerRow key={item.delivery_id} item={item} />)}
      </section>

      <div className="summary-actions">
        <button type="button" className="secondary-action" onClick={onBack}>受信箱へ</button>
        {readyNext && (
          <button type="button" className="primary-action" disabled={start.isPending} onClick={() => start.mutate(readyNext.core_session_id)}>
            次を聴く（残り {readyCount}）
          </button>
        )}
      </div>
      {start.isError && <p className="inline-error">{humanError(start.error)}</p>}
    </main>
  );
}

function AnswerRow({ item }: { item: RelistenItemView }) {
  const preference = item.skipped ? null : item.judgment?.preference ?? null;
  const note = answerNote(item);
  return (
    <div className="answer-table-row">
      <span>{item.sequence_index + 1}</span>
      <span className="answer-gauge" aria-label={preference === null ? "回答なし" : preferenceText(preference)}>
        {([1, 2, 3, 4, 5] as const).map((value) => <span key={value} className={preference === value ? "active" : ""} />)}
      </span>
      <strong className={preference === 3 ? "answer-judgment neutral" : "answer-judgment"}>{preference === null ? "skip" : preferenceText(preference)}</strong>
      <span className="answer-note" title={note}>{note}</span>
    </div>
  );
}

function preferenceText(preference: 1 | 2 | 3 | 4 | 5): string {
  return ["明確にA", "わずかにA", "互角", "わずかにB", "明確にB"][preference - 1] ?? "";
}

function answerNote(item: RelistenItemView): string {
  if (item.skipped) return "skip";
  if (!item.judgment) return "";
  const notes: string[] = [];
  for (const slot of ["a", "b"] as const) {
    const blocker = item.judgment.blockers[slot];
    if (!blocker?.selected) continue;
    const name = slot.toUpperCase();
    notes.push(`${name}に問題${blocker.note ? `（${blocker.note}）` : ""}`);
  }
  if (item.judgment.comment) notes.push(item.judgment.comment);
  return notes.join(" · ");
}

function verdictCopy(data: SessionCompletion): { title: string; detail: string } {
  const result = data.result;
  if (!result) return { title: "比較を記録しました", detail: "結果はProject Sessionへ記録されていません。" };
  if (data.current_best_check) {
    return result.current_best_updated
      ? { title: `現在最良を ${result.favored_variant_label ?? "提案版"} に更新しました`, detail: "" }
      : { title: "現在最良を維持します", detail: "" };
  }
  const favored = result.favored_variant_label ? `${result.favored_variant_label} が優勢` : "互角";
  return {
    title: "観察として記録しました（現在最良は変わりません）",
    detail: `${favored} · 差の傾向 ${differenceLabel(result.difference_profile)}`,
  };
}

function differenceLabel(value: string): string {
  return { clear: "明確", mixed: "混在", subtle: "微妙" }[value] ?? value;
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
