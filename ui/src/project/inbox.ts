import type { SessionCardView } from "../generated";

/* 受信箱の振り分け(§8.2)。開始できなかったSessionは完了に混ぜず、理由付きで独立に見せる(C10: 静かな停止の禁止)。 */

export type InboxSessions = {
  /** active → paused → ready の順。 */
  pending: SessionCardView[];
  /** 開始前の検証で止まったSession(`blocked`)。開けないが、理由を読める所に置く。 */
  blocked: SessionCardView[];
  /** 終了したSession(`done`)。結果を読み取り専用で開ける。 */
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
    completed: sessions.filter((item) => item.status === "done"),
  };
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
 * 「未回答」の欄が空のときの一文。聴くもの・確かめるものが残っているときは出さない。
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
