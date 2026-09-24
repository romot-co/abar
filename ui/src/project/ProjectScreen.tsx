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
    <div className="nibi-select nibi-select--quiet project-picker">
      <select
        className="nibi-select__native"
        aria-label="プロジェクト"
        value={workspaces.selected_id}
        disabled={switchingWorkspace}
        onChange={(event) => onSelectWorkspace(event.currentTarget.value)}
      >
        {workspaces.workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
        ))}
      </select>
    </div>
  );
  const otherWorkspaces = workspaces.workspaces.length > 1;

  if (project.health.status === "degraded") {
    return (
      <main className="screen">
        {otherWorkspaces && <header className="inbox-header">{picker}</header>}
        <section className="nibi-card nibi-card--lead error-panel">
          <h1>Workspaceを読み込めません</h1>
          <p>{project.health.degradation?.recovery ?? project.health.reasons?.join("、")}</p>
        </section>
      </main>
    );
  }

  const lifecycleError = start.isError || resume.isError ? <p className="inline-error" role="alert">{humanError(start.error ?? resume.error)}</p> : null;
  // Projectに属さない進行中のSessionがあれば、それが次にすること(主操作)になる。
  const continueOther = otherSession && (
    <section className="nibi-card nibi-card--lead lead-card" aria-labelledby="other-session-heading">
      <span className="card-kicker">{otherSession.status === "paused" ? "一時停止中" : "試聴中"}</span>
      <h2 id="other-session-heading" className="lead-title">進行中の試聴</h2>
      <p className="card-meta">Projectに属さない比較（abar listen）を続けられます。</p>
      {otherSession.status === "paused" ? (
        <button type="button" className="nibi-button nibi-button--primary primary-action lead-action" disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(otherSession.sessionId); }}>再開</button>
      ) : (
        <button type="button" className="nibi-button nibi-button--primary primary-action lead-action" onClick={onOpenDeck}>続きを聴く</button>
      )}
    </section>
  );

  if (project.project_id === null) {
    return (
      <main className="screen">
        {otherWorkspaces && <header className="inbox-header">{picker}</header>}
        <h1 className="page-title">Projectはまだありません</h1>
        {continueOther}
        {lifecycleError}
        <section className="nibi-card empty-state" aria-label="はじめかた">
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
  // 先頭のSessionを次に聴くものとして大きく出す(主操作は画面に一つ)。進行中の試聴があればそちらが先。
  const lead = otherSession ? null : pending[0] ?? null;
  const rest = lead ? pending.slice(1) : pending;
  const sessionAction = (item: SessionCardView, primary: boolean) => {
    const className = primary ? "nibi-button nibi-button--primary primary-action lead-action" : "nibi-button secondary-action";
    if (item.status === "active") return <button type="button" className={className} onClick={onOpenDeck}>続きを聴く</button>;
    if (item.status === "paused") {
      return <button type="button" className={className} disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(item.project_session_id); }}>再開</button>;
    }
    return (
      <button type="button" className={className} disabled={blocked || start.isPending} onClick={() => { resume.reset(); start.mutate(item.project_session_id); }}>
        聴く
      </button>
    );
  };

  return (
    <main className="screen inbox">
      <header className="inbox-header">
        {picker}
        <p className="brief">{project.brief}</p>
      </header>

      {continueOther}
      <section className="queue-section" aria-labelledby="queue-heading">
        {project.pending_simplifications.map((prompt) => (
          <SimplificationPrompt key={prompt.id} prompt={prompt} pending={decide.isPending} onDecision={(decision) => decide.mutate({ id: prompt.id, decision })} />
        ))}
        {decide.isError && <p className="inline-error" role="alert">{humanError(decide.error)}</p>}
        <div className="section-heading">
          <h2 id="queue-heading">残りのセッション</h2>
          <span className="count">{pending.length}</span>
        </div>
        {lead && (
          <article className="nibi-card nibi-card--lead lead-card queue-lead" aria-labelledby="queue-lead-focus">
            <span className="card-kicker">次に聴く · {sessionKind(lead)}</span>
            <h3 id="queue-lead-focus" className="lead-title">{lead.topic_key && <span className="topic-key">{lead.topic_key} · </span>}{lead.focus}</h3>
            <p className="card-meta">{sessionMeta(lead, project.primary_recipe ?? "")}</p>
            {sessionAction(lead, true)}
          </article>
        )}
        {rest.length > 0 && (
          <div className="nibi-card queue-list">
            {rest.map((item) => (
              <QueueRow key={item.project_session_id} session={item} primaryRecipe={project.primary_recipe ?? ""}>
                {sessionAction(item, false)}
              </QueueRow>
            ))}
          </div>
        )}
        {pending.length === 0 && (
          <div className="nibi-card nibi-card--lead empty-queue">
            <strong>全て判定済みです</strong>
            <span>エージェントの次の提案を待っています。新しいセッションが準備されるとここに並びます。</span>
          </div>
        )}
        {blocked && pending.some((item) => item.status === "ready") && (
          <p className="nibi-note-text queue-hint">進行中のセッションを完了すると、次のセッションを聴けます</p>
        )}
        {lifecycleError}
      </section>

      {completed.length > 0 && (
        <details className="disclosure completed-sessions">
          <summary><Icon name="chevron_right" />完了したセッション {completed.length} 件を見る</summary>
          <div className="nibi-card completed-list">
            {completed.map((item) => {
              const content = (
                <>
                  <span className="completed-main">
                    <span className="card-kicker"><span className="completed-date">{formatDate(item.completed_at)}</span> · {sessionKind(item)}</span>
                    <p>{item.focus}</p>
                  </span>
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
        <div className="nibi-card nibi-card--lead state-card">
          <strong className="best-id">{project.current_best}</strong>
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
      <h3 className="group-label">{label}</h3>
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
        {role === "guard" && (
          <span className={`nibi-badge guard-badge ${item.guard_result ?? "unknown"}${item.guard_result === "fail" ? " nibi-badge--error" : ""}`}>
            {item.guard_result === "fail" && <Icon name="warning" />}
            {formatGuardResult(item.guard_result)}
          </span>
        )}
      </span>
    </div>
  );
}

function QueueRow({ session, primaryRecipe, children }: { session: SessionCardView; primaryRecipe: string; children?: ReactNode }) {
  return (
    <div className="queue-row">
      <div className="queue-body">
        <span className={session.current_best_check ? "card-kicker queue-kind featured" : "card-kicker queue-kind"}>{sessionKind(session)}</span>
        <p className="queue-focus">{session.topic_key && <span className="topic-key">{session.topic_key} · </span>}{session.focus}</p>
        <span className="queue-recipe">{sessionMeta(session, primaryRecipe)}</span>
      </div>
      {children ?? <span className="queue-outcome">{session.status === "done" ? "完了" : session.status}</span>}
    </div>
  );
}

function sessionKind(session: SessionCardView): string {
  return session.current_best_check ? "現在最良チェック" : "観察";
}

function sessionMeta(session: SessionCardView, primaryRecipe: string): string {
  const answered = session.answered_count > 0 ? `${session.answered_count}/${session.comparison_count} 回答済み` : `${session.comparison_count} 比較`;
  const recipe = session.recipe === primaryRecipe
    ? `Recipe ${session.recipe}`
    : `Recipe ${session.recipe}（Project既定: ${primaryRecipe}）`;
  return `${answered} · ${recipe}`;
}

function SimplificationPrompt({ prompt, pending, onDecision }: { prompt: SimplificationPromptView; pending: boolean; onDecision: (decision: "accept" | "keep") => void }) {
  // 採用も維持も人間の判断なので、どちらかを主操作にしない。
  return (
    <section className="nibi-card nibi-card--lead simplification-prompt" aria-labelledby={`simplification-${prompt.id}`}>
      <span className="card-kicker">提案</span>
      <h2 id={`simplification-${prompt.id}`} className="lead-title">指定範囲で同一の音でした</h2>
      <p className="card-meta">{prompt.reason}</p>
      <div className="pair-actions">
        <button type="button" className="nibi-button secondary-action" disabled={pending} onClick={() => onDecision("keep")}>維持する</button>
        <button type="button" className="nibi-button secondary-action" disabled={pending} onClick={() => onDecision("accept")}>採用する</button>
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
