/*
 * 候補名の短縮(handoff PROPOSAL 3.3)。結果の集計・表の見出しと、Deckで中身を表示したA/Bのカードで同じ規則を使う。
 * 候補名はagentが付けるので長く、違いは一部の語だけのことが多い(`… Depth 100 (F80 GMoff); 20260926` と `… Depth 60 …`)。
 *
 * 1. 空白で語に分ける。語の数が同じなら、違う語だけを取り出す。続いて違う語は一つの塊にし、
 *    塊の直前の語が項目名(文字を含み、括弧や ; を含まない)なら一緒に残す(「Depth 100」)。塊が複数なら「 · 」でつなぐ。
 * 2. 語の数が違うときは、前後の共通の語を落とした残りを使う(直前の語が項目名なら残す)。片方が空になるときは、
 *    共通の語を一つずつ戻す。
 * 3. 同じ名前、または全部の語が違うときは正式名のまま。
 * 正式名は消さない(title属性と「候補の正式名」の開閉)。
 */

export type NameToken = { text: string; differs: boolean };
export type CandidateName = { full: string; short: string; tokens: NameToken[] };

/** 軸の名前にそのまま使える短縮名の長さ(文字数)。超えたら「候補 1 / 2」に置き換える。 */
export const AXIS_NAME_MAX = 12;

const NOT_LABEL = /[;:()（）[\]{}]/;

function words(name: string): string[] {
  return name.trim().split(/\s+/).filter(Boolean);
}

function isLabel(word: string | undefined): boolean {
  if (!word || NOT_LABEL.test(word) || word.endsWith(",")) return false;
  return /\p{L}/u.test(word);
}

function whole(full: string, tokens: string[], differs: boolean): CandidateName {
  return { full, short: full, tokens: tokens.map((text) => ({ text, differs })) };
}

function byPosition(full: string, tokens: string[], differs: boolean[]): CandidateName {
  const groups: string[] = [];
  let index = 0;
  while (index < tokens.length) {
    if (!differs[index]) { index += 1; continue; }
    const start = index;
    while (index < tokens.length && differs[index]) index += 1;
    const label = start > 0 && isLabel(tokens[start - 1]) ? `${tokens[start - 1]} ` : "";
    groups.push(label + tokens.slice(start, index).join(" "));
  }
  return { full, short: groups.join(" · "), tokens: tokens.map((text, i) => ({ text, differs: differs[i] ?? false })) };
}

export function shortenPair(left: string, right: string): [CandidateName, CandidateName] {
  const a = words(left);
  const b = words(right);
  if (left.trim() === right.trim() || a.length === 0 || b.length === 0) return [whole(left, a, false), whole(right, b, false)];
  if (a.length === b.length) {
    const differs = a.map((word, i) => word !== b[i]);
    const count = differs.filter(Boolean).length;
    if (count > 0 && count < a.length) return [byPosition(left, a, differs), byPosition(right, b, differs)];
  }
  let prefix = 0;
  while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < a.length - prefix && suffix < b.length - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix += 1;
  // 片方の残りが空なら、共通の語を前から(なければ後ろから)一つずつ戻す。
  while (prefix + suffix >= Math.min(a.length, b.length) && (prefix > 0 || suffix > 0)) {
    if (prefix > 0) prefix -= 1;
    else suffix -= 1;
  }
  if (prefix === 0 && suffix === 0) return [whole(left, a, true), whole(right, b, true)];
  const part = (full: string, tokens: string[]): CandidateName => {
    const end = tokens.length - suffix;
    const label = prefix > 0 && isLabel(tokens[prefix - 1]) ? `${tokens[prefix - 1]} ` : "";
    return {
      full,
      short: label + tokens.slice(prefix, end).join(" "),
      tokens: tokens.map((text, i) => ({ text, differs: i >= prefix && i < end })),
    };
  };
  return [part(left, a), part(right, b)];
}

export type AxisNames = {
  left: string;
  right: string;
  /** 短縮名が長く「候補 1 / 2」に置き換えた(対応は集計の欄に一度だけ出す)。 */
  aliased: boolean;
};

/**
 * 左右の軸の名前(図と表の見出し、1行に収める)。Plan付きは役割(現在最良 / 提案)、
 * 観察は短縮名。どちらかが AXIS_NAME_MAX 字を超えるときは「候補 1」「候補 2」。
 */
export function axisNames(left: CandidateName, right: CandidateName, plan: boolean): AxisNames {
  if (plan) return { left: "現在最良", right: "提案", aliased: false };
  if ([...left.short].length > AXIS_NAME_MAX || [...right.short].length > AXIS_NAME_MAX) {
    return { left: "候補 1", right: "候補 2", aliased: true };
  }
  return { left: left.short, right: right.short, aliased: false };
}
