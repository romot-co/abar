import { useMutation } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { api, type Action, type Project, type WorkspaceCatalog } from "../api";
import { humanError } from "../errors";
import type { IndicatorSummaryView, SessionCardView, SimplificationPromptView } from "../generated";
import { Icon } from "../Icon";

/** Projectの受信箱に載らない進行中のSession(`abar listen` のQuick Listen等)。 */
export type OtherSession = { sessionId: string; status: "active" | "paused" };

type ProjectScreenProps = {
  project: Project;
  otherSession: OtherSession | null;
  workspaces: WorkspaceCatalog;
  switchingWorkspace: boolean;
  onSelectWorkspace: (workspaceId: string) => void;
  onOpenDeck: () => void;
  onOpenCompletion: (coreSessionId: string) => void;
  onChanged: () => void;
};

export function ProjectScreen({ project, otherSession, workspaces, switchingWorkspace, onSelectWorkspace, onOpenDeck, onOpenCompletion, onChanged }: ProjectScreenProps) {
  const start = useMutation({
    mutationFn: (sessionId: string) =>
      api<Action>(`/api/sessions/${sessionId}/start`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => { onChanged(); onOpenDeck(); },
  });
  const resume = useMutation({
    mutationFn: (sessionId: string) => api<Action>(`/api/sessions/${sessionId}/resume`, { method: "POST" }),
    onSuccess: () => { onChanged(); onOpenDeck(); },
  });
  const inProgress = [
    ...project.sessions.filter((item) => item.status === "active" || item.status === "paused").map((item) => item.project_session_id),
    ...(otherSession ? [otherSession.sessionId] : []),
  ].join(",");
  const { reset: resetStart } = start;
  const { reset: resetResume } = resume;
  // 進行中のSessionが変わったら、前の開始・再開エラー(409等)はもう当てはまらない。
  useEffect(() => { resetStart(); resetResume(); }, [inProgress, resetStart, resetResume]);
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "accept" | "keep" }) => api<Action>(`/api/simplifications/${id}/decision`, { method: "POST", body: JSON.stringify({ decision }) }),
    onSuccess: onChanged,
  });

  // 読み込めないWorkspaceやProjectのないWorkspaceからも、他のProjectへ戻れるようにする。
  const picker = (
    <div className="project-picker">
      <select
        aria-label="プロジェクト"
        value={workspaces.selected_id}
        disabled={switchingWorkspace}
        onChange={(event) => onSelectWorkspace(event.currentTarget.value)}
      >
        {workspaces.workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
        ))}
      </select>
      <Icon name="unfold_more" />
    </div>
  );
  const otherWorkspaces = workspaces.workspaces.length > 1;

  if (project.health.status === "degraded") {
    return (
      <main className="page-shell">
        {otherWorkspaces && <header className="inbox-header">{picker}</header>}
        <section className="centered error-panel">
          <h1>Workspaceを読み込めません</h1>
          <p>{project.health.degradation?.recovery ?? project.health.reasons?.join("、")}</p>
        </section>
      </main>
    );
  }

  const lifecycleError = start.isError || resume.isError ? <p className="inline-error" role="alert">{humanError(start.error ?? resume.error)}</p> : null;
  const continueOther = otherSession && (
    <section className="queue-section" aria-labelledby="other-session-heading">
      <div className="section-heading">
        <h2 id="other-session-heading">進行中の試聴</h2>
      </div>
      <div className="queue-list">
        <div className="queue-row">
          <div className="queue-body">
            <span className="queue-kind featured">{otherSession.status === "paused" ? "一時停止中" : "試聴中"}</span>
            <p className="queue-focus">Projectに属さない比較（abar listen）を続けられます。</p>
          </div>
          {otherSession.status === "paused" ? (
            <button type="button" className="primary-action" disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(otherSession.sessionId); }}>再開</button>
          ) : (
            <button type="button" className="primary-action" onClick={onOpenDeck}>続きを聴く</button>
          )}
        </div>
      </div>
    </section>
  );

  if (project.project_id === null) {
    return (
      <main className="page-shell">
        {otherWorkspaces && <header className="inbox-header">{picker}</header>}
        <header className="page-header">
          <h1>Projectはまだありません</h1>
        </header>
        {continueOther}
        {lifecycleError}
        <section className="empty-state" aria-label="はじめかた">
          <code>abar project init --name "製品名" --brief "目的" --material path/to/audio.wav</code>
        </section>
      </main>
    );
  }

  const pending = project.sessions
    .filter((item) => item.status === "active" || item.status === "paused" || item.status === "ready")
    .sort((left, right) => sessionRank(left.status) - sessionRank(right.status));
  const completed = project.sessions.filter(
    (item) => item.status === "done" || item.status === "blocked",
  );
  // Sessionは同時に一つだけ進行できる。進行中・一時停止中があるあいだ、新しいSessionは開始できない。
  const blocked = inProgress !== "";
  const targets = project.indicators.filter((item) => item.role === "target");
  const guards = project.indicators.filter((item) => item.role === "guard");

  return (
    <main className="page-shell inbox">
      <header className="inbox-header">
        {picker}
        <p className="brief">{project.brief}</p>
      </header>

      {continueOther}
      <section className="queue-section" aria-label="残りのセッション">
        {project.pending_simplifications.map((prompt) => (
          <SimplificationPrompt key={prompt.id} prompt={prompt} pending={decide.isPending} onDecision={(decision) => decide.mutate({ id: prompt.id, decision })} />
        ))}
        {decide.isError && <p className="inline-error" role="alert">{humanError(decide.error)}</p>}
        <div className="section-heading">
          <h2>残りのセッション</h2>
          <span className="count">{pending.length}</span>
        </div>
        {pending.length > 0 ? (
          <div className="queue-list">
            {pending.map((item, index) => (
              <QueueRow key={item.project_session_id} session={item} primaryRecipe={project.primary_recipe ?? ""}>
                {item.status === "ready" && (
                  <button type="button" className={index === 0 && !otherSession ? "primary-action" : "secondary-action"} disabled={blocked || start.isPending} onClick={() => { resume.reset(); start.mutate(item.project_session_id); }}>
                    聴く
                  </button>
                )}
                {item.status === "active" && (
                  <button type="button" className="primary-action" onClick={onOpenDeck}>続きを聴く</button>
                )}
                {item.status === "paused" && (
                  <button type="button" className={index === 0 ? "primary-action" : "secondary-action"} disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(item.project_session_id); }}>再開</button>
                )}
              </QueueRow>
            ))}
          </div>
        ) : (
          <div className="empty-queue">
            <strong>全て判定済みです</strong>
            <span>エージェントの次の提案を待っています。新しいセッションが準備されるとここに並びます。</span>
          </div>
        )}
        {blocked && pending.some((item) => item.status === "ready") && (
          <p className="submit-hint queue-hint">進行中のセッションを完了すると、次のセッションを聴けます</p>
        )}
        {lifecycleError}
      </section>

      {completed.length > 0 && (
        <details className="disclosure completed-sessions">
          <summary>完了したセッション {completed.length} 件を見る</summary>
          <div className="completed-list">
            {completed.map((item) => {
              const content = (
                <>
                  <span className="completed-date">{formatDate(item.completed_at)}</span>
                  <p><span>{item.current_best_check ? "現在最良チェック" : "観察"}</span>{item.focus}</p>
                  <strong>{item.status === "blocked" ? "準備できず" : item.outcome ?? "完了"}</strong>
                </>
              );
              return item.status === "blocked" ? (
                <div className="completed-row" key={item.project_session_id} title={item.outcome ?? undefined}>{content}</div>
              ) : (
                <button
                  type="button"
                  className="completed-row"
                  key={item.project_session_id}
                  aria-label={`結果を見る: ${item.focus}`}
                  onClick={() => onOpenCompletion(item.project_session_id)}
                >
                  {content}
                </button>
              );
            })}
          </div>
        </details>
      )}

      <section className="current-best-section" aria-labelledby="current-best-heading">
        <div className="section-heading">
          <h2 id="current-best-heading">現在最良</h2>
        </div>
        <div className="state-card">
          <div className="state-stats">
            <strong className="best-id">{project.current_best}</strong>
          </div>
          {(targets.length > 0 || guards.length > 0) && (
            <div className="indicator-groups">
              {targets.length > 0 && <IndicatorGroup label="目標" role="target" items={targets} />}
              {guards.length > 0 && <IndicatorGroup label="ガード" role="guard" items={guards} />}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function IndicatorGroup({ label, role, items }: { label: string; role: "target" | "guard"; items: IndicatorSummaryView[] }) {
  return (
    <div className="indicator-group">
      <span className="group-label">{label}</span>
      <div className="indicator-rows">
        {items.map((item) => <IndicatorRow key={item.id} item={item} role={role} />)}
      </div>
    </div>
  );
}

function IndicatorRow({ item, role }: { item: IndicatorSummaryView; role: "target" | "guard" }) {
  const unit = item.unit === "ratio" ? "" : ` ${item.unit}`;
  return (
    <div className="indicator-row">
      <span className="indicator-label">{item.label}</span>
      <p className="indicator-description">{item.description}</p>
      <span className="indicator-value"><strong>{formatIndicatorValue(item.value)}</strong>{unit}</span>
      <span className="indicator-status">
        {role === "guard" && <span className={`guard-badge ${item.guard_result ?? "unknown"}`}>{formatGuardResult(item.guard_result)}</span>}
      </span>
    </div>
  );
}

function QueueRow({ session, primaryRecipe, children }: { session: SessionCardView; primaryRecipe: string; children?: ReactNode }) {
  const answered = session.answered_count > 0 ? ` · ${session.answered_count}/${session.comparison_count} 回答済み` : ` · ${session.comparison_count} 比較`;
  const recipe = session.recipe === primaryRecipe
    ? `Recipe ${session.recipe}`
    : `Recipe ${session.recipe}（Project既定: ${primaryRecipe}）`;
  return (
    <div className="queue-row">
      <div className="queue-body">
        <span className={session.current_best_check ? "queue-kind featured" : "queue-kind"}>
          {session.current_best_check ? "現在最良チェック" : "観察"}{answered}
        </span>
        <p className="queue-focus">{session.topic_key && <span>{session.topic_key} · </span>}{session.focus}</p>
        <span className="queue-recipe">{recipe}</span>
      </div>
      {children ?? <span className="queue-outcome">{session.status === "done" ? "完了" : session.status}</span>}
    </div>
  );
}

function SimplificationPrompt({ prompt, pending, onDecision }: { prompt: SimplificationPromptView; pending: boolean; onDecision: (decision: "accept" | "keep") => void }) {
  return (
    <section className="simplification-prompt">
      <h2>指定範囲で同一の音でした</h2>
      <p className="brief">{prompt.reason}</p>
      <div>
        <button type="button" className="primary-action" disabled={pending} onClick={() => onDecision("accept")}>採用する</button>
        <button type="button" className="secondary-action" disabled={pending} onClick={() => onDecision("keep")}>維持する</button>
      </div>
    </section>
  );
}

function sessionRank(status: SessionCardView["status"]): number {
  return { active: 0, paused: 1, ready: 2, done: 3, closed: 4, blocked: 5 }[status];
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function formatIndicatorValue(value: number | null): string {
  if (value === null) return "—";
  return String(Math.round(value * 1_000) / 1_000);
}

function formatGuardResult(result: IndicatorSummaryView["guard_result"]): string {
  if (result === "pass") return "クリア";
  if (result === "fail") return "問題あり";
  return "未確認";
}
