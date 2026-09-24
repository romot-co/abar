import { ApiError } from "./api";

const BY_CODE: Record<string, string> = {
  capability_rejected:
    "このブラウザはまだ接続されていません。`abar ui` が表示するURLから一度開いてください。",
  host_rejected: "このアドレスからは接続できません。`abar ui` が表示するURLから開いてください。",
  origin_rejected: "このページからの操作は受け付けられません。`abar ui` が表示するURLから開いてください。",
  audio_token_invalid: "音声の再生リンクが期限切れです。画面を更新してください。",
  judgment_already_recorded: "この比較は回答済みです。回答は一度だけ記録できます。",
  session_not_active: "Sessionが進行中ではないため、この操作は行えません。画面を更新してください。",
  delivery_already_answered: "回答済みの比較は飛ばせません。",
  session_already_active: "別のSessionが進行中です。先にそちらを完了してください。",
  duplicate_session: "同じ条件の未完了Sessionが既にあります。",
  session_not_ready: "このSessionは開始できる状態ではありません。",
  project_session_blocked: "証拠音声を検証できなかったため、このSessionは開始できません。",
  delivery_already_skipped: "飛ばした比較には回答できません。",
  skip_confirmation_required: "この比較を飛ばすには確認が必要です。",
  human_required: "この操作には人間の権限が必要です。",
  idempotency_conflict: "同じ操作が異なる内容で送られました。画面を更新してやり直してください。",
  entity_not_found: "対象が見つかりません。画面を更新してください。",
  request_invalid: "送信内容が正しくありません。画面を更新してやり直してください。",
  request_rejected: "この操作は現在の状態では受け付けられません。画面を更新して状態を確認してください。",
  command_rejected: "この操作は現在の状態では受け付けられません。画面を更新して状態を確認してください。",
  workspace_degraded: "Workspaceを読み込めません。`abar status` で状態を確認してください。",
  workspace_error: "Workspaceを操作できませんでした。画面を更新してやり直してください。",
};

const NETWORK_MESSAGE = "ABARサーバーに接続できません。`abar ui` が起動しているか確認して再試行してください。";

/** fetch自体の失敗(サーバー停止・回線断)。HTTPエラー応答とは区別する。 */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

export function humanError(error: unknown): string {
  if (error instanceof ApiError) {
    return BY_CODE[error.code] ?? `操作を完了できませんでした（${error.code}）。画面を更新してやり直してください。`;
  }
  if (isNetworkError(error)) return NETWORK_MESSAGE;
  return "予期しないエラーが発生しました。画面を更新してやり直してください。";
}

export function isSkipConfirmationRequired(error: unknown): boolean {
  return error instanceof ApiError && error.code === "skip_confirmation_required";
}
