import type { RelistenItemView, SessionResultView } from "../generated";

/*
 * 結果のゲージと支持の図の向き(§8.3)。A/Bの割り付けは比較ごとに違うので、A/Bの位置で描くと同じ形が逆の支持を表してしまう。
 * 終了したSessionの結果画面だけで(A/Bと候補の対応はここで初めて公開できる、§7.9)、両端を候補に固定する。
 *   Plan付き: 左 = 開始時の現在最良(incumbent)、右 = 提案(proposed)
 *   一般:     左 / 右 = Sessionの組(pair)の順
 *   Projectに属さない試聴: 最初の比較の A / B の中身。中身が分からなければ A / B のまま
 */

export type GaugeEnd = { key: string; label: string; role: string | null };
export type GaugeEnds = { left: GaugeEnd; right: GaugeEnd; bySlot: boolean };
export type Preference = 1 | 2 | 3 | 4 | 5;

type Identity = RelistenItemView["identity_by_slot"][string];

/** 比較の一方の中身を候補の鍵にする。Variantは`variant_ref`(原音は`source`)、それ以外は音声ID。 */
export function identityKey(identity: Identity | undefined): string | null {
  if (!identity) return null;
  const ref = identity.provenance?.variant_ref;
  if (typeof ref === "string" && ref) return ref;
  if (identity.provenance?.kind === "source") return "source";
  return identity.audio_id || null;
}

export function identityLabel(identity: Identity | undefined): string {
  if (!identity) return "unknown";
  if (typeof identity.label === "string" && identity.label) return identity.label;
  const provenance = identity.provenance as Record<string, unknown> | undefined;
  if (provenance) return String(provenance.variant_ref ?? provenance.name ?? provenance.audio_id ?? identity.audio_id ?? "audio");
  return String(identity.audio_id ?? "audio");
}

const SLOT_ENDS: GaugeEnds = {
  left: { key: "A", label: "A", role: null },
  right: { key: "B", label: "B", role: null },
  bySlot: true,
};

export function gaugeEnds(result: SessionResultView | null, items: readonly RelistenItemView[]): GaugeEnds {
  if (result) {
    const [first, second, ...rest] = Object.keys(result.variant_labels);
    if (first !== undefined && second !== undefined && rest.length === 0) {
      const proposed = result.best_update_evidence?.proposed_variant_id ?? null;
      const end = (key: string, role: string | null): GaugeEnd => ({ key, label: result.variant_labels[key] ?? key, role });
      if (proposed === first || proposed === second) {
        const incumbent = proposed === first ? second : first;
        return { left: end(incumbent, "開始時の現在最良"), right: end(proposed, "提案"), bySlot: false };
      }
      return { left: end(first, null), right: end(second, null), bySlot: false };
    }
  }
  for (const item of items) {
    const a = identityKey(item.identity_by_slot.A);
    const b = identityKey(item.identity_by_slot.B);
    if (a && b && a !== b) {
      return {
        left: { key: a, label: identityLabel(item.identity_by_slot.A), role: null },
        right: { key: b, label: identityLabel(item.identity_by_slot.B), role: null },
        bySlot: false,
      };
    }
  }
  return SLOT_ENDS;
}

export type OrientedAnswer =
  /** 選んだ段を左右の端に合わせた位置(1 = 左を明確に、5 = 右を明確に)。 */
  | { kind: "directed"; position: Preference }
  /** 両側が同じ音(同一音の確認)か、どちらの端か分からない: 向きを持たず、強さだけを左右対称に示す。 */
  | { kind: "symmetric"; distance: 0 | 1 | 2 }
  | { kind: "missing" };

export function orientAnswer(item: RelistenItemView, ends: GaugeEnds, preference: Preference | null): OrientedAnswer {
  if (preference === null) return { kind: "missing" };
  if (ends.bySlot) return { kind: "directed", position: preference };
  const a = identityKey(item.identity_by_slot.A);
  const b = identityKey(item.identity_by_slot.B);
  if (a === ends.left.key && b === ends.right.key) return { kind: "directed", position: preference };
  if (a === ends.right.key && b === ends.left.key) return { kind: "directed", position: (6 - preference) as Preference };
  return { kind: "symmetric", distance: Math.abs(preference - 3) as 0 | 1 | 2 };
}

export type Strength = "clear" | "slight";

/*
 * 比較ごとのゲージ(handoff PROPOSAL 3.2)。支持の図(3.1)を比較1つ分で描く: 中央の縦線から支持した側へ、
 * わずか = ブロック1つ(薄く低い)、明確 = ブロック2つ(濃く高い)。互角は中央の点、飛ばした・未回答は何も描かない。
 * 図の下に必ず言葉を添える(色と形だけにしない)。
 */
export type RowGauge = {
  side: "left" | "right" | "center" | null;
  blocks: Strength[];
  word: "明確" | "わずか" | "互角" | "差を報告" | "飛ばした" | "未回答";
};

export function rowGauge(answer: OrientedAnswer, skipped = false): RowGauge {
  if (answer.kind === "missing") return { side: null, blocks: [], word: skipped ? "飛ばした" : "未回答" };
  if (answer.kind === "symmetric") {
    if (answer.distance === 0) return { side: "center", blocks: [], word: "互角" };
    return { side: "center", blocks: [], word: "差を報告" };
  }
  if (answer.position === 3) return { side: "center", blocks: [], word: "互角" };
  const clear = answer.position === 1 || answer.position === 5;
  return {
    side: answer.position < 3 ? "left" : "right",
    blocks: clear ? ["clear", "clear"] : ["slight"],
    word: clear ? "明確" : "わずか",
  };
}

/*
 * 支持の図(handoff PROPOSAL 3.1)の形。中央から左右へ、支持した比較1件ごとにブロックを1つ置く(中央に近い方から明確、わずか)。
 * ブロックの幅は片側の幅を比較の数(slots)で割った大きさ。優勢に必要な件数の位置に、中央から左右同じ距離で縦線を引く
 * (位置は全体の幅に対する割合: 左 0.5 − threshold × 0.5、右 0.5 + threshold × 0.5)。互角と未回答はブロックにしない。
 */
export type SupportChart = {
  left: Strength[];
  right: Strength[];
  /** 片側に並べられるブロックの数(= 比較の数)。 */
  slots: number;
  /** 必要な件数 ÷ 比較の数(0〜1)。 */
  threshold: number;
  /** 必要な件数の縦線の位置(全体の幅に対する割合)。 */
  tickLeft: number;
  tickRight: number;
};

export function supportChart(answers: readonly OrientedAnswer[], required: number, evidenceCount: number): SupportChart {
  const left: Strength[] = [];
  const right: Strength[] = [];
  for (const answer of answers) {
    if (answer.kind !== "directed" || answer.position === 3) continue;
    const strength: Strength = answer.position === 1 || answer.position === 5 ? "clear" : "slight";
    (answer.position < 3 ? left : right).push(strength);
  }
  const order = (items: Strength[]) => [...items.filter((item) => item === "clear"), ...items.filter((item) => item === "slight")];
  const slots = Math.max(1, evidenceCount, left.length, right.length);
  const threshold = Math.min(1, Math.max(0, required / slots));
  return { left: order(left), right: order(right), slots, threshold, tickLeft: 0.5 - threshold * 0.5, tickRight: 0.5 + threshold * 0.5 };
}

/** ゲージの読み上げ(と見た目の意味): 端の名前へ正規化した支持。 */
export function answerWords(answer: OrientedAnswer, ends: GaugeEnds): string {
  if (answer.kind === "missing") return "未回答";
  if (answer.kind === "symmetric") return answer.distance === 0 ? "差なし" : `差を報告（${answer.distance === 2 ? "明確" : "わずか"}）`;
  if (answer.position === 3) return "互角";
  const end = answer.position < 3 ? ends.left : ends.right;
  const strength = answer.position === 1 || answer.position === 5 ? "明確に" : "わずかに";
  return `${end.label} を${strength}支持`;
}
