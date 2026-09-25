import type { SessionResultView } from "../generated";

/*
 * 結論カードの「優勢」の行(§5.4・§4.3)。「優勢条件 2 / 3」は何が何件か読めないので、件数と必要数を言葉にする。
 * standard の優勢: evidence の3分の2以上(端数切上げ)が同じ向き、かつ強さの合計(明確 ±2、わずか ±1)が正。
 * Plan付き: 提案の向きが必要数以上、強さの合計が正、全件回答、提案に残せない問題なし(§4.3)。
 * 条件に届かないのは普通の結果(現在最良を維持)なので、失敗(fail)の印を使わない。
 */

export type ReasonKind = "pass" | "unknown";
export type ConditionReason = { kind: ReasonKind; text: string };

export function conditionReason(result: SessionResultView): ConditionReason {
  const required = result.favored_required_count;
  const evidence = result.best_update_evidence;
  if (evidence) {
    const proposed = result.variant_labels[evidence.proposed_variant_id] ?? "提案";
    const notes: string[] = [];
    if (evidence.answered_count < evidence.evidence_count) notes.push(`${evidence.evidence_count - evidence.answered_count}件は未回答`);
    if (evidence.favorable_count >= required && evidence.score_sum <= 0) notes.push("強さの合計が正でない");
    const met = evidence.answered_count === evidence.evidence_count && evidence.favorable_count >= required && evidence.score_sum > 0;
    return {
      kind: met ? "pass" : "unknown",
      text: `提案（${proposed}）を支持: ${evidence.evidence_count}件中${evidence.favorable_count}件（必要 ${required}件）${notes.length ? `、${notes.join("、")}` : ""}`,
    };
  }
  const counts = Object.keys(result.variant_labels).map((key) => ({ key, count: result.evidence_direction_counts[key] ?? 0 }));
  const leader = counts.reduce<{ key: string; count: number } | null>((best, entry) => (best === null || entry.count > best.count ? entry : best), null);
  if (result.favored_variant_id !== null) {
    const count = result.evidence_direction_counts[result.favored_variant_id] ?? 0;
    const label = result.favored_variant_label ?? result.variant_labels[result.favored_variant_id] ?? "一方";
    return { kind: "pass", text: `${label}が優勢: ${result.evidence_count}件中${count}件（必要 ${required}件）` };
  }
  const tied = leader !== null && counts.filter((entry) => entry.count === leader.count).length > 1;
  const most = leader === null || leader.count === 0
    ? "どちらの支持もなし"
    : tied
      ? `最多は${leader.count}件ずつ`
      : `最多は${result.variant_labels[leader.key]}の${leader.count}件`;
  const scoreNote = leader !== null && !tied && leader.count >= required ? "、強さの合計が正でない" : "";
  return { kind: "unknown", text: `どちらも優勢に届かない: ${result.evidence_count}件中、${most}（必要 ${required}件）${scoreNote}` };
}
