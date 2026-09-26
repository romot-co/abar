import type { SessionResultView } from "../generated";
import type { GaugeEnds } from "./gauge";

/*
 * 結果の結論(§8.3): 見出し1つと、それを支える文1つ。件数と必要数は言葉で言う(「2 / 3」のような読めない形にしない)。
 * 更新しなかった・優勢に届かなかったときは、どの条件で止まったかを支える文で言う(C10: 止まった理由を隠さない)。
 * standard の優勢: evidence の3分の2以上(端数切上げ)が同じ向き、かつ強さの合計(明確 ±2、わずか ±1)が正。
 * Plan付き: 提案の向きが必要数以上、強さの合計が正、全件回答、提案に残せない問題なし(§4.3)。
 * favored=null は一律に互角と言わない: 全比較で互角、回答の不足、判断の分裂、優勢条件の未達を分ける。
 */

export type Conclusion = { headline: string; detail: string };

/** 候補の鍵 → 画面で使う名前(軸の名前)。 */
export type AxisLabels = { left: string; right: string };

export function conclusion(result: SessionResultView | null, ends: GaugeEnds, axis: AxisLabels, proposedName: string | null): Conclusion {
  if (!result) {
    return { headline: "比較を記録しました", detail: "この試聴はProjectに属さないため、現在最良は変わりません。" };
  }
  const required = result.favored_required_count;
  const total = result.evidence_count;
  const evidence = result.best_update_evidence;
  if (evidence) {
    if (result.current_best_updated) {
      return {
        headline: proposedName ? `現在最良を ${proposedName} に更新しました` : "現在最良を提案に更新しました",
        detail: `提案を支持した比較は ${evidence.evidence_count} 件中 ${evidence.favorable_count} 件でした（必要 ${required} 件）。`,
      };
    }
    return { headline: "現在最良を維持しました", detail: keepReason(result) };
  }
  const nameOf = (key: string) => (key === ends.left.key ? axis.left : key === ends.right.key ? axis.right : result.variant_labels[key] ?? key);
  const counts = Object.keys(result.variant_labels).map((key) => ({ key, count: result.evidence_direction_counts[key] ?? 0 }));
  const ties = result.evidence_direction_counts.tie ?? 0;
  const need = `優勢には ${total} 件中 ${required} 件が必要です。`;
  const unchanged = "現在最良は変わりません。";
  if (result.favored_variant_id !== null) {
    return { headline: `${nameOf(result.favored_variant_id)} が優勢でした`, detail: `${need}${unchanged}` };
  }
  if (total > 0 && ties === total) return { headline: "全比較で互角でした", detail: `${need}${unchanged}` };
  const leader = counts.reduce<{ key: string; count: number } | null>((best, entry) => (best === null || entry.count > best.count ? entry : best), null);
  if (leader === null || leader.count === 0) {
    return { headline: "判定できる回答が不足しています", detail: `${need}${unchanged}` };
  }
  if (counts.filter((entry) => entry.count === leader.count).length > 1) {
    return { headline: "判断が素材によって分かれました", detail: `${need}${unchanged}` };
  }
  const detail = leader.count >= required
    ? `支持は ${total} 件中 ${leader.count} 件で必要数に届きましたが、強さの合計が正でないため優勢になりませんでした。${unchanged}`
    : `${need}${unchanged}`;
  return { headline: `${nameOf(leader.key)} の支持が多いが、優勢には届きませんでした`, detail };
}

// 更新しなかった理由を、サーバーの判定順(未回答 → 問題の報告 → 必要数 → 強さの合計)に合わせて一つだけ言う。
function keepReason(result: SessionResultView): string {
  const evidence = result.best_update_evidence;
  const required = result.favored_required_count;
  if (!evidence) return "";
  if (evidence.answered_count < evidence.evidence_count) return "飛ばした比較があるため、更新の条件を満たしませんでした。";
  if (evidence.blocker_count > 0) return "提案に残せない問題が報告されたため、更新しませんでした。";
  if (evidence.favorable_count < required) {
    return `提案を支持した比較は ${evidence.evidence_count} 件中 ${evidence.favorable_count} 件で、更新に必要な ${required} 件に届きませんでした。`;
  }
  if (evidence.score_sum <= 0) return "提案への支持が反対の回答を上回らず、更新の条件を満たしませんでした。";
  return `更新には ${evidence.evidence_count} 件中 ${required} 件の支持が必要です。`;
}
