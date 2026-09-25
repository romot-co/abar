import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type Action, type Project, type WorkspaceCatalog } from "../api";
import { humanError } from "../errors";
import type { IndicatorSummaryView, SessionCardView, SimplificationPromptView } from "../generated";
import { Icon } from "../Icon";
import { Mark } from "../Mark";
import { blockedReason, classifySessions, queueMessage } from "./inbox";

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

const cols = (value: string) => ({ "--nibi-rowlist-cols": value }) as CSSProperties;

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
  const [completedOpen, setCompletedOpen] = useState(false);

  // 題名がそのままProjectの選択になる。読み込めないWorkspaceやProjectのないWorkspaceからも他へ戻れる。
  const selectedName = workspaces.workspaces.find((workspace) => workspace.id === workspaces.selected_id)?.name ?? "ABAR";
  const picker = (
    <label className="nibi-title-select project-picker">
      <span className="nibi-title nibi-title-select__value">{selectedName}</span>
      <span className="nibi-title-select__disc" aria-hidden="true"><Icon name="chevron_down" /></span>
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
    </label>
  );

  if (project.health.status === "degraded") {
    return (
      <main className="screen inbox">
        <header className="inbox-header">{picker}</header>
        <section className="nibi-notice error-panel" role="alert">
          <div className="nibi-notice__text">
            <h1 className="nibi-heading notice-title">Workspaceを読み込めません</h1>
            <p className="nibi-body">{project.health.degradation?.recovery ?? project.health.reasons?.join("、")}</p>
          </div>
        </section>
      </main>
    );
  }

  const lifecycleError = start.isError || resume.isError ? <p className="inline-error" role="alert">{humanError(start.error ?? resume.error)}</p> : null;
  // Projectに属さない進行中の試聴も「未回答」の先頭に並べる(続けるのが次の一手)。
  const otherRow = otherSession && (
    <div className="nibi-rowlist__row queue-row">
      <span className="nibi-rowlist__title nibi-body">
        <span className="nibi-rowlist__name">Projectに属さない比較（abar listen）</span>
        <span className="nibi-rowlist__sub">{otherSession.status === "paused" ? "一時停止中" : "試聴中"}</span>
      </span>
      <span className="nibi-rowlist__end">
        {otherSession.status === "paused" ? (
          <button type="button" className="nibi-button" disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(otherSession.sessionId); }}>再開</button>
        ) : (
          <button type="button" className="nibi-button nibi-button--primary" onClick={onOpenDeck}>続ける</button>
        )}
      </span>
    </div>
  );

  if (project.project_id === null) {
    return (
      <main className="screen inbox">
        <header className="inbox-header">
          {picker}
          <p className="nibi-body brief">Projectはまだありません。</p>
        </header>
        {otherRow && (
          <section className="inbox-section" aria-labelledby="queue-heading">
            <h2 id="queue-heading" className="section-title">未回答</h2>
            <div className="nibi-rowlist nibi-rowlist--emph-name nibi-rowlist--start nibi-rowlist--stack queue-list" role="group" aria-label="未回答のセッション" style={cols("minmax(0, 1fr) auto")}>{otherRow}</div>
          </section>
        )}
        {lifecycleError}
        <section className="nibi-card empty-state" aria-label="はじめかた">
          <code>abar project init --name "製品名" --brief "目的" --material path/to/audio.wav</code>
        </section>
      </main>
    );
  }

  const { pending, blocked: blockedSessions, completed } = classifySessions(project.sessions);
  const emptyQueue = queueMessage({
    pendingCount: pending.length,
    otherSession: otherSession !== null,
    blockedCount: blockedSessions.length,
    confirmationCount: project.pending_simplifications.length,
  });
  // Sessionは同時に一つだけ進行できる。進行中・一時停止中があるあいだ、新しいSessionは開始できない。
  const blocked = inProgress !== "";
  const targets = project.indicators.filter((item) => item.role === "target");
  const guards = project.indicators.filter((item) => item.role === "guard");
  const sessionAction = (item: SessionCardView): ReactNode => {
    if (item.status === "active") return <button type="button" className="nibi-button nibi-button--primary" onClick={onOpenDeck}>続ける</button>;
    if (item.status === "paused") {
      return <button type="button" className="nibi-button" disabled={resume.isPending} onClick={() => { start.reset(); resume.mutate(item.project_session_id); }}>再開</button>;
    }
    if (blocked) return <span className="nibi-note-text blocked-note">進行中の完了後</span>;
    return <button type="button" className="nibi-button" disabled={start.isPending} onClick={() => { resume.reset(); start.mutate(item.project_session_id); }}>開始</button>;
  };

  return (
    <main className="screen inbox">
      <header className="inbox-header">
        {picker}
        <p className="nibi-body brief">{project.brief}</p>
      </header>

      <section className="inbox-section current-best-section" aria-labelledby="current-best-heading">
        <div className="best-heading">
          <h2 id="current-best-heading" className="nibi-label best-label">現在最良</h2>
          <strong className="nibi-title best-id">{project.current_best}</strong>
        </div>
        {(targets.length > 0 || guards.length > 0) && (
          <div
            className="nibi-rowlist nibi-rowlist--line nibi-rowlist--striped nibi-rowlist--emph-name nibi-rowlist--start nibi-rowlist--stack state-card indicator-table"
            role="table"
            aria-label="現在最良の指標"
            style={cols("minmax(0, 1fr) auto 7rem")}
          >
            {targets.length > 0 && <IndicatorGroup label="目標" role="target" items={targets} />}
            {guards.length > 0 && <IndicatorGroup label="制約" role="guard" items={guards} />}
          </div>
        )}
      </section>

      <section className="inbox-section queue-section" aria-labelledby="queue-heading">
        <h2 id="queue-heading" className="section-title">未回答</h2>
        {emptyQueue && <p className="nibi-body empty-queue">{emptyQueue}</p>}
        {(pending.length > 0 || otherRow) && (
          <div className="nibi-rowlist nibi-rowlist--emph-name nibi-rowlist--start nibi-rowlist--stack queue-list" role="group" aria-label="未回答のセッション" style={cols("minmax(0, 1fr) auto")}>
            {otherRow}
            {pending.map((item) => (
              <div className="nibi-rowlist__row queue-row" key={item.project_session_id} aria-disabled={item.status === "ready" && blocked ? true : undefined}>
                <span className="nibi-rowlist__title nibi-body">
                  <span className="nibi-rowlist__name queue-focus">{item.focus}</span>
                  <span className="nibi-rowlist__sub">{sessionKind(item)}{item.topic_key ? ` · ${item.topic_key}` : ""}</span>
                </span>
                <span className="nibi-rowlist__end">{sessionAction(item)}</span>
              </div>
            ))}
          </div>
        )}
        {lifecycleError}
        {project.pending_simplifications.map((prompt) => (
          <SimplificationNotice key={prompt.id} prompt={prompt} pending={decide.isPending} onDecision={(decision) => decide.mutate({ id: prompt.id, decision })} />
        ))}
        {decide.isError && <p className="inline-error" role="alert">{humanError(decide.error)}</p>}
      </section>

      {blockedSessions.length > 0 && (
        <section className="inbox-section blocked-section" aria-labelledby="blocked-heading">
          <h2 id="blocked-heading" className="section-title">開始できない {blockedSessions.length} 件</h2>
          <div className="nibi-rowlist nibi-rowlist--emph-name nibi-rowlist--start nibi-rowlist--stack blocked-list" role="list" aria-label="開始できないセッション" style={cols("minmax(0, 1fr) auto")}>
            {blockedSessions.map((item) => (
              <div className="nibi-rowlist__row blocked-row" role="listitem" key={item.project_session_id}>
                <span className="nibi-rowlist__title nibi-body">
                  <span className="nibi-rowlist__name queue-focus">{item.focus}</span>
                  <span className="nibi-rowlist__sub">{sessionKind(item)}{item.completed_at ? ` · ${formatDate(item.completed_at)}` : ""}</span>
                  <span className="nibi-rowlist__sub blocked-reason">理由: {blockedReason(item.outcome)}</span>
                </span>
                <span className="nibi-rowlist__status nibi-body blocked-status"><Mark kind="fail" /><span className="blocked-word">開始できません</span></span>
              </div>
            ))}
          </div>
        </section>
      )}

      {completed.length > 0 && (
        <section className="inbox-section completed-section">
          <div className="nibi-disclosure nibi-disclosure--link completed-sessions">
            <button
              type="button"
              className="nibi-disclosure__header"
              aria-expanded={completedOpen}
              aria-controls="completed-region"
              onClick={() => setCompletedOpen((open) => !open)}
            >
              <Icon name="chevron_right" className="nibi-disclosure__chevron" />完了 {completed.length} 件を見る
            </button>
            <div id="completed-region" className="nibi-disclosure__region" hidden={!completedOpen}>
              <div className="nibi-rowlist nibi-rowlist--line nibi-rowlist--start completed-list" role="group" aria-label="完了したセッション" style={cols("3rem minmax(0, 1fr) auto")}>
                {completed.map((item) => (
                  <button
                    type="button"
                    className="nibi-rowlist__row completed-row"
                    key={item.project_session_id}
                    aria-label={`結果を見る: ${item.focus}`}
                    onClick={() => onOpenCompletion(item.project_session_id)}
                  >
                    <span className="nibi-value completed-date">{formatDate(item.completed_at)}</span>
                    <span className="nibi-rowlist__title nibi-body" title={item.focus}>
                      <span className="nibi-rowlist__name">{item.focus}</span>
                      <span className="nibi-rowlist__sub">{sessionKind(item)}</span>
                    </span>
                    <span className="nibi-rowlist__end nibi-body completed-outcome">
                      {item.outcome ?? "完了"}
                      <Icon name="chevron_right" />
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}

function IndicatorGroup({ label, role, items }: { label: string; role: "target" | "guard"; items: IndicatorSummaryView[] }) {
  return (
    <>
      <div className="nibi-rowlist__group indicator-group" role="row">
        <span role="columnheader" className="nibi-rowlist__group-title"><h3 className="nibi-label group-label">{label}</h3></span>
        <span role="columnheader" />
        <span role="columnheader" />
      </div>
      {items.map((item) => <IndicatorRow key={item.id} item={item} role={role} />)}
    </>
  );
}

function IndicatorRow({ item, role }: { item: IndicatorSummaryView; role: "target" | "guard" }) {
  const unit = item.unit === "ratio" ? "" : item.unit;
  return (
    <div className="nibi-rowlist__row indicator-row" role="row">
      <span role="rowheader" className="nibi-rowlist__title nibi-body indicator-label"><span className="nibi-rowlist__name">{item.label}</span></span>
      <span role="cell" className="nibi-rowlist__num nibi-body indicator-value">
        <span className="indicator-number">{formatIndicatorValue(item.value)}</span>
        {unit && <span className="nibi-rowlist__unit">{unit}</span>}
      </span>
      <span role="cell" className="nibi-rowlist__status nibi-body indicator-status">
        {role === "guard" && <GuardStatus result={item.guard_result} />}
      </span>
    </div>
  );
}

function GuardStatus({ result }: { result: IndicatorSummaryView["guard_result"] }) {
  if (result === "pass") return <span className="guard-badge pass"><Mark kind="pass" />合格</span>;
  if (result === "fail") return <span className="guard-badge fail"><Mark kind="fail" /><span className="guard-fail-word">不合格</span></span>;
  return <span className="guard-badge unknown"><Mark kind="unknown" />未測定</span>;
}

function SimplificationNotice({ prompt, pending, onDecision }: { prompt: SimplificationPromptView; pending: boolean; onDecision: (decision: "accept" | "keep") => void }) {
  // 採用も維持も人間の判断なので、どちらかを主操作にしない。
  return (
    <div className="nibi-notice simplification-prompt" role="group" aria-labelledby={`simplification-${prompt.id}`}>
      <p className="nibi-notice__text nibi-body">
        <strong id={`simplification-${prompt.id}`} className="notice-title">同一の音でした。単純な方へまとめますか。</strong>
        <span className="nibi-label notice-reason">{prompt.reason}</span>
      </p>
      <div className="nibi-notice__actions">
        <button type="button" className="nibi-button" disabled={pending} onClick={() => onDecision("keep")}>分けたまま</button>
        <button type="button" className="nibi-button" disabled={pending} onClick={() => onDecision("accept")}>まとめる</button>
      </div>
    </div>
  );
}

function sessionKind(session: SessionCardView): string {
  return session.current_best_check ? "最良の更新" : "観察";
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
