import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type Action, type Project, type WorkspaceCatalog } from "../api";
import { ClampedText } from "../ClampedText";
import { humanError } from "../errors";
import type { IndicatorSummaryView, SessionCardView, SimplificationPromptView } from "../generated";
import { Icon } from "../Icon";
import { Mark } from "../Mark";
import { blockedReason, classifySessions, leadCopy, queueMessage, selectLead, splitHistory, type Lead, type OtherSession } from "./inbox";
import { decimalsByUnit, displayUnit, formatIndicatorValue } from "./indicators";
import { InlineError } from "../InlineError";

export type { OtherSession } from "./inbox";

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

/*
 * 受信箱(§8.2): 人間が次に聴くものを選ぶ画面。
 * 題名の選択と目的 → 次の一手の面(進行中・一時停止中、なければ最初の準備済み)→ 確認(単純化)→ このあと N 件(各行に自分の操作)
 * → 開始できない N 件(理由を文で)→ これまで(新しい順、行を押すと結果)。横の欄に現在最良と指標。900px 未満は1列で、
 * 現在最良は「このあと」の次。
 */
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

  // 題名(頁のh1)がそのままProjectの選択になる。読み込めないWorkspaceやProjectのないWorkspaceからも他へ戻れる。
  // 見出しの名前は題名の文字だけ(中の選択肢の値を重ねて読まない)。
  const selectedName = workspaces.workspaces.find((workspace) => workspace.id === workspaces.selected_id)?.name ?? "ABAR";
  const picker = (
    <h1 className="project-title" aria-labelledby="project-title-text">
      <label className="nibi-title-select project-picker">
        <span id="project-title-text" className="nibi-display nibi-title-select__value">{selectedName}</span>
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
    </h1>
  );

  if (project.health.status === "degraded") {
    return (
      <main className="screen inbox">
        <header className="inbox-header">{picker}</header>
        <section className="nibi-notice error-panel" role="alert">
          <div className="nibi-notice__text">
            <h2 className="nibi-heading notice-title">Workspaceを読み込めません</h2>
            <p className="nibi-body">{project.health.degradation?.recovery ?? project.health.reasons?.join("、")}</p>
          </div>
        </section>
      </main>
    );
  }

  const lifecycleError = start.isError || resume.isError ? <InlineError>{humanError(start.error ?? resume.error)}</InlineError> : null;
  const pendingAction = start.isPending || resume.isPending;
  const openLead = (lead: Lead) => {
    const id = lead.kind === "other" ? lead.session.sessionId : lead.session.project_session_id;
    const status = lead.session.status;
    if (status === "active") { onOpenDeck(); return; }
    if (status === "paused") { start.reset(); resume.mutate(id); return; }
    resume.reset();
    start.mutate(id);
  };

  const { pending, blocked: blockedSessions, completed } = classifySessions(project.sessions);
  const { lead, rest } = selectLead(project.project_id === null ? [] : pending, otherSession);
  const leadPanel = lead && <LeadPanel lead={lead} pending={pendingAction} onAction={() => openLead(lead)} />;

  if (project.project_id === null) {
    return (
      <main className="screen inbox">
        <header className="inbox-header">
          {picker}
          <p className="nibi-body brief">Projectはまだありません。</p>
        </header>
        {leadPanel}
        {lifecycleError}
        <section className="nibi-card empty-state" aria-label="はじめかた">
          <code>abar project init --name "製品名" --brief "目的" --material path/to/audio.wav</code>
        </section>
      </main>
    );
  }

  const emptyQueue = lead ? null : queueMessage({
    pendingCount: pending.length,
    otherSession: otherSession !== null,
    blockedCount: blockedSessions.length,
    confirmationCount: project.pending_simplifications.length,
  });
  // Sessionは同時に一つだけ進行できる。進行中・一時停止中があるあいだ、新しいSessionは開始できない(理由を語で)。
  const busy = inProgress !== "";
  const rowAction = (item: SessionCardView): ReactNode => {
    if (item.status === "paused") {
      return <button type="button" className="nibi-button" disabled={pendingAction} onClick={() => { start.reset(); resume.mutate(item.project_session_id); }}>再開</button>;
    }
    if (busy) return <span className="nibi-note-text blocked-note">進行中の完了後</span>;
    return <button type="button" className="nibi-button" disabled={pendingAction} onClick={() => { resume.reset(); start.mutate(item.project_session_id); }}>開始</button>;
  };

  return (
    <main className="screen inbox">
      <header className="inbox-header">
        {picker}
        <p className={project.brief ? "nibi-body brief" : "nibi-body brief missing"}>{project.brief || "目的はまだ書かれていません。"}</p>
      </header>

      <div className="inbox-layout">
        <div className="inbox-main">
          {leadPanel && <div className="inbox-lead">{leadPanel}{lifecycleError}</div>}
          {(project.pending_simplifications.length > 0 || decide.isError) && (
            <div className="inbox-notices">
              {project.pending_simplifications.map((prompt) => (
                <SimplificationNotice key={prompt.id} prompt={prompt} pending={decide.isPending} onDecision={(decision) => decide.mutate({ id: prompt.id, decision })} />
              ))}
              {decide.isError && <InlineError>{humanError(decide.error)}</InlineError>}
            </div>
          )}

          {(rest.length > 0 || emptyQueue) && (
            <section className="inbox-section queue-section" aria-labelledby="queue-heading">
              <h2 id="queue-heading" className="nibi-heading section-title">
                このあと{rest.length > 0 && <span className="heading-count"> {rest.length} 件</span>}
              </h2>
              {emptyQueue && <p className="nibi-body empty-queue">{emptyQueue}</p>}
              {!leadPanel && lifecycleError}
              {rest.length > 0 && (
                <ol className="nibi-rowlist nibi-rowlist--bare nibi-rowlist--prose nibi-rowlist--ruled queue-list" aria-label="このあとのセッション">
                  {rest.map((item, index) => (
                    <li className="nibi-rowlist__row queue-row" key={item.project_session_id} aria-disabled={item.status === "ready" && busy ? true : undefined}>
                      <span className="nibi-rowlist__num nibi-value queue-index">{index + 1}</span>
                      <span className="nibi-rowlist__title nibi-rowlist__title--plain nibi-body queue-focus" title={item.focus}>{item.focus}</span>
                      <span className="nibi-rowlist__end queue-end">
                        <span className="nibi-body queue-kind">{sessionKind(item)} · {item.comparison_count} 比較</span>
                        {rowAction(item)}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}

          {blockedSessions.length > 0 && (
            <section className="inbox-section blocked-section" aria-labelledby="blocked-heading">
              <h2 id="blocked-heading" className="nibi-heading section-title">開始できない {blockedSessions.length} 件</h2>
              <ul className="nibi-rowlist nibi-rowlist--bare nibi-rowlist--prose nibi-rowlist--ruled blocked-list" aria-label="開始できないセッション" style={cols("minmax(0, 1fr) auto")}>
                {blockedSessions.map((item) => (
                  <li className="nibi-rowlist__row blocked-row" key={item.project_session_id}>
                    <span className="nibi-rowlist__title nibi-rowlist__title--plain nibi-body">
                      <span className="nibi-rowlist__name blocked-focus">{item.focus}</span>
                      <span className="nibi-rowlist__sub">{sessionKind(item)}{item.completed_at ? ` · ${formatDate(item.completed_at)}` : ""}</span>
                      <span className="nibi-rowlist__sub blocked-reason">理由: {blockedReason(item.outcome)}</span>
                    </span>
                    <span className="nibi-rowlist__status nibi-body blocked-status"><Mark kind="fail" /><span className="blocked-word">開始できません</span></span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {completed.length > 0 && <History completed={completed} onOpen={onOpenCompletion} />}
        </div>

        <aside className="nibi-panel inbox-side" aria-labelledby="current-best-heading">
          <CurrentBest project={project} />
        </aside>
      </div>
    </main>
  );
}

/* 次の一手の面(nibi 0014 D-2、`.nibi-panel--lead`): 画面に1つ。中身はその一手と主ボタンだけ。 */
function LeadPanel({ lead, pending, onAction }: { lead: Lead; pending: boolean; onAction: () => void }) {
  const copy = leadCopy(lead);
  const session = lead.kind === "project" ? lead.session : null;
  const step = copy.step;
  return (
    <section className="nibi-panel nibi-panel--lead lead-panel" aria-labelledby="lead-heading">
      <div className="lead-top">
        <h2 id="lead-heading" className="nibi-heading">{copy.heading}</h2>
        {session && <span className="nibi-label lead-kind">{sessionKind(session)} · {session.comparison_count} 比較</span>}
      </div>
      <div className="lead-question">
        <ClampedText className="nibi-lead lead-focus">
          {session ? session.focus : "Projectに属さない比較（abar listen）"}
        </ClampedText>
      </div>
      <div className="lead-bottom">
        {step && (
          <span className="lead-progress">
            {step.total <= 20 && (
              <span className="nibi-progress" aria-hidden="true">
                {Array.from({ length: step.total }, (_, index) => (
                  <span key={index} className="nibi-progress__seg" data-done={index < step.current - 1 ? "" : undefined} data-current={index === step.current - 1 ? "" : undefined} />
                ))}
              </span>
            )}
            <span className="nibi-value lead-count" aria-label={`回答済み ${step.current - 1} / ${step.total}`}>{step.current - 1} / {step.total}</span>
          </span>
        )}
        <button type="button" className="nibi-button nibi-button--primary lead-action" disabled={pending} onClick={onAction}>{copy.action}</button>
      </div>
    </section>
  );
}

function CurrentBest({ project }: { project: Project }) {
  const targets = project.indicators.filter((item) => item.role === "target");
  const guards = project.indicators.filter((item) => item.role === "guard");
  const decimals = decimalsByUnit([...targets, ...guards]);
  const hasUnits = [...targets, ...guards].some((item) => displayUnit(item.unit) !== "");
  return (
    <>
      <div className="best-heading">
        <h2 id="current-best-heading" className="nibi-heading section-title">現在最良</h2>
        <p className="nibi-body best-id">{project.current_best ?? "—"}</p>
      </div>
      {targets.length === 0 && guards.length === 0 ? (
        <p className="nibi-body indicators-empty">指標はまだありません。</p>
      ) : (
        <div
          className="nibi-rowlist nibi-rowlist--bare nibi-rowlist--prose nibi-rowlist--ruled indicator-table"
          role="table"
          aria-label="現在最良の指標"
          style={cols("minmax(0, 1fr) auto")}
        >
          {targets.length > 0 && <IndicatorGroup label="目標" role="target" items={targets} decimals={decimals} hasUnits={hasUnits} />}
          {guards.length > 0 && <IndicatorGroup label="守る性質" role="guard" items={guards} decimals={decimals} hasUnits={hasUnits} />}
        </div>
      )}
    </>
  );
}

type ValueFormat = { decimals: Map<string, number>; hasUnits: boolean };

function IndicatorGroup({ label, role, items, decimals, hasUnits }: { label: string; role: "target" | "guard"; items: IndicatorSummaryView[] } & ValueFormat) {
  return (
    <>
      <div className="nibi-rowlist__group indicator-group" role="row">
        <span role="columnheader" className="nibi-rowlist__group-title"><h3 className="nibi-label group-label">{label}</h3></span>
        <span role="columnheader" />
      </div>
      {items.map((item) => <IndicatorRow key={item.id} item={item} role={role} decimals={decimals} hasUnits={hasUnits} />)}
    </>
  );
}

// 名前は折り返し、値は右寄せ(同じ単位は小数の桁を揃える、単位は揃えた数字の外)。守る性質の判定は名前の下に印と語で。
function IndicatorRow({ item, role, decimals, hasUnits }: { item: IndicatorSummaryView; role: "target" | "guard" } & ValueFormat) {
  const unit = displayUnit(item.unit);
  return (
    <div className="nibi-rowlist__row indicator-row" role="row">
      <span role="rowheader" className="nibi-rowlist__title nibi-rowlist__title--plain nibi-body indicator-label">
        <span className="nibi-rowlist__name">{item.label}</span>
        {role === "guard" && <span className="indicator-status"><GuardStatus result={item.guard_result} /></span>}
      </span>
      <span role="cell" className="nibi-rowlist__num nibi-body indicator-value">
        <span className="indicator-number">{formatIndicatorValue(item.value, decimals.get(item.unit) ?? 0)}</span>
        {hasUnits && <span className="nibi-rowlist__unit indicator-unit">{unit}</span>}
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
  // 採用も維持も人間の判断なので、どちらかを主操作にしない。見出しは付けない(1文 + 理由)。
  return (
    <div className="nibi-notice simplification-prompt" role="group" aria-labelledby={`simplification-${prompt.id}`}>
      <p className="nibi-notice__text nibi-body">
        <strong id={`simplification-${prompt.id}`} className="notice-title">同一の音でした。単純な方へまとめますか。</strong>
        <span className="notice-reason">{prompt.reason}</span>
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

/* これまで(§8.2): 新しい順。最初の HISTORY_VISIBLE 件は開いたまま、それより古い回は「残り N 件を見る」の開閉の中
   (nibi の開閉は重要でない履歴に使う、SPEC §6.7)。開くとその場で下に続く。 */
function History({ completed, onOpen }: { completed: SessionCardView[]; onOpen: (sessionId: string) => void }) {
  const [open, setOpen] = useState(false);
  const { shown, folded } = splitHistory(completed);
  const rows = (items: SessionCardView[], label: string) => (
    <div className="nibi-rowlist nibi-rowlist--bare nibi-rowlist--prose nibi-rowlist--ruled history-list" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          type="button"
          className="nibi-rowlist__row history-row"
          key={item.project_session_id}
          aria-label={`結果を見る: ${item.focus}`}
          onClick={() => onOpen(item.project_session_id)}
        >
          <span className="nibi-rowlist__num nibi-value history-date">{formatDate(item.completed_at)}</span>
          <span className="nibi-body history-focus" title={item.focus}>{item.focus}</span>
          <span className={item.current_best_updated ? "nibi-body history-outcome updated" : "nibi-body history-outcome"}>
            <span className="history-mark">{item.current_best_updated && <Mark kind="pass" />}</span>
            <span className="history-words">{item.outcome ?? "完了"}</span>
          </span>
        </button>
      ))}
    </div>
  );
  return (
    <section className="inbox-section history-section" aria-labelledby="history-heading">
      <h2 id="history-heading" className="nibi-heading section-title">これまで</h2>
      {rows(shown, "完了したセッション")}
      {folded.length > 0 && (
        <div className="nibi-disclosure nibi-disclosure--link history-more">
          <button type="button" className="nibi-disclosure__header" aria-expanded={open} aria-controls="history-older" onClick={() => setOpen((value) => !value)}>
            <Icon name="chevron_right" className="nibi-disclosure__chevron" />
            残り {folded.length} 件を見る
          </button>
          <div id="history-older" className="nibi-disclosure__region" hidden={!open}>
            {open && rows(folded, "それより前の完了したセッション")}
          </div>
        </div>
      )}
    </section>
  );
}

