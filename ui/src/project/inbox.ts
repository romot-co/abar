import type { SessionCardView } from "../generated";

/** Projectの受信箱に載らない進行中のSession(`abar listen` のQuick Listen等)。 */
export type OtherSession = { sessionId: string; status: "active" | "paused" };

/* 受信箱の振り分け(§8.2)。開始できなかったSessionは完了に混ぜず、理由付きで独立に見せる(C10: 静かな停止の禁止)。 */

export type InboxSessions = {
  /** active → paused → ready の順。 */
  pending: SessionCardView[];
  /** 開始前の検証で止まったSession(`blocked`)。開けないが、理由を読める所に置く。 */
  blocked: SessionCardView[];
  /** 終了したSession(`done`)。結果を読み取り専用で開ける。新しい順。 */
  completed: SessionCardView[];
};

const PENDING_RANK: Partial<Record<SessionCardView["status"], number>> = { active: 0, paused: 1, ready: 2 };

export function classifySessions(sessions: readonly SessionCardView[]): InboxSessions {
  const pending = sessions
    .filter((item) => PENDING_RANK[item.status] !== undefined)
    .sort((left, right) => (PENDING_RANK[left.status] ?? 0) - (PENDING_RANK[right.status] ?? 0));
  return {
    pending,
    blocked: sessions.filter((item) => item.status === "blocked"),
    completed: sessions
      .filter((item) => item.status === "done")
      .map((item, index) => ({ item, index }))
      .sort((left, right) => completedTime(right.item) - completedTime(left.item) || right.index - left.index)
      .map(({ item }) => item),
  };
}

function completedTime(item: SessionCardView): number {
  const time = item.completed_at ? Date.parse(item.completed_at) : Number.NaN;
  return Number.isNaN(time) ? 0 : time;
}

/*
 * 次の一手の面(§8.2、nibi 0014 D-2)に載せる一つ。進行中・一時停止中の試聴があればそれ(Projectに属さないものも含む。
 * 同時に進められるSessionは一つ)、なければ最初の準備済み。残りは「このあと」に並べ、各行が自分の操作を持つ。
 */
export type Lead =
  | { kind: "other"; session: OtherSession }
  | { kind: "project"; session: SessionCardView };

export function selectLead(pending: readonly SessionCardView[], other: OtherSession | null): { lead: Lead | null; rest: SessionCardView[] } {
  if (other) return { lead: { kind: "other", session: other }, rest: [...pending] };
  const [first, ...rest] = pending;
  return first ? { lead: { kind: "project", session: first }, rest } : { lead: null, rest: [] };
}

export type LeadCopy = {
  /** 面の見出し。 */
  heading: "途中の試聴" | "次に聴く";
  /** 主ボタンの文言。 */
  action: string;
  /** 途中なら今の比較の番号(1始まり)と比較の数。 */
  step: { current: number; total: number } | null;
};

export function leadCopy(lead: Lead): LeadCopy {
  if (lead.kind === "other") return { heading: "途中の試聴", action: "続きから", step: null };
  const { status, answered_count: answered, comparison_count: total } = lead.session;
  if (status === "ready") return { heading: "次に聴く", action: "聴きはじめる", step: null };
  const current = Math.min(Math.max(answered + 1, 1), Math.max(total, 1));
  return { heading: "途中の試聴", action: `続きから（${current} / ${total}）`, step: { current, total } };
}

export type QueueState = {
  pendingCount: number;
  /** Projectに属さない進行中の試聴があるか。 */
  otherSession: boolean;
  blockedCount: number;
  /** 回答を待つ単純化の確認の数。 */
  confirmationCount: number;
};

/**
 * 聴くものが一つもないときの一文(「このあと」の欄に出す)。聴くもの・確かめるものが残っているときは出さない。
 * 「全て判定済み」は、未回答・開始できない・確認待ちのどれもないときだけ(開始できないSessionを判定済みと言わない)。
 */
export function queueMessage(state: QueueState): string | null {
  if (state.pendingCount > 0 || state.otherSession || state.confirmationCount > 0) return null;
  if (state.blockedCount > 0) return "開始できるセッションはありません。";
  return "全て判定済みです。新しいセッションが準備されるとここに並びます。";
}

// サーバーの止まった理由(session.blocked の reason)を、受信箱で読める言葉へ。知らない理由はそのまま出す。
const BLOCKED_REASONS: Record<string, string> = {
  "Session audio validation failed": "比較する音声を検証できませんでした（欠落または内容の不一致）",
};

export function blockedReason(outcome: string | null | undefined): string {
  if (!outcome) return "理由は記録されていません";
  return BLOCKED_REASONS[outcome] ?? outcome;
}

/** これまでの欄で開いたまま見せる件数。それより古い回は「残り N 件を見る」に畳む(100件を超える台帳を1画面に並べない)。 */
export const HISTORY_VISIBLE = 3;

/** 新しい順の完了を、常に見せる分と畳む分に分ける。 */
export function splitHistory<T>(completed: readonly T[], visible = HISTORY_VISIBLE): { shown: T[]; folded: T[] } {
  return { shown: completed.slice(0, visible), folded: completed.slice(visible) };
}

