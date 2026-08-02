import { ApiError } from "./api";

const BY_CODE: Record<string, string> = {
  capability_rejected:
    "このブラウザはまだ接続されていません。`abar ui` が表示するURLから一度開いてください。",
  audio_token_invalid: "音声の再生リンクが期限切れです。画面を更新してください。",
  judgment_already_recorded: "この比較は回答済みです。回答は一度だけ記録できます。",
  session_not_active: "Sessionが進行中ではないため、この操作は行えません。",
  delivery_already_answered: "回答済みの比較はskipできません。",
  project_session_already_active:
    "別のSessionが進行中です。先にそちらを終えるか一時停止してください。",
  duplicate_session: "同じ条件の未完了Sessionが既にあります。",
  session_not_ready: "このSessionは開始できる状態ではありません。",
  project_session_blocked: "証拠音声を検証できなかったため、このSessionは開始できません。",
  skip_confirmation_required:
    "この比較は現在最良の判断に使う証拠です。skipするには確認が必要です。",
  human_required: "この操作には人間の権限が必要です。",
  idempotency_conflict: "同じ操作キーが異なる内容に再利用されました。",
};

export function humanError(error: unknown): string {
  if (error instanceof ApiError) {
    return BY_CODE[error.code] ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return "不明なエラーが発生しました";
}

export function isSkipConfirmationRequired(error: unknown): boolean {
  return error instanceof ApiError && error.code === "skip_confirmation_required";
}
