import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Action, type Deck, type Judgment } from "../api";
import { humanError, isNetworkError, isSkipConfirmationRequired } from "../errors";
import { useComparisonPlayer } from "../useComparisonPlayer";
import { EMPTY_DRAFT, buildRequest, type AnswerDraft } from "./answerDraft";
import { AnswerDock, AnswerEditor, DeckHeader, ListeningPanel, PausedPanel, SkipConfirmBar } from "./DeckPanels";
import { SessionSummary } from "./SessionSummary";
import { useDeckShortcuts } from "./useDeckShortcuts";

type Keyed<T> = { deliveryId: string | null; value: T };

export function DeckScreen({ onBack }: { onBack: () => void }) {
  const queryClient = useQueryClient();
  const [deck, setDeck] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // 下書き・skip確認・完了済みはdeliveryごとに持つ。deliveryが変わった最初の描画から前の比較の値を出さない。
  const [draftState, setDraftState] = useState<Keyed<AnswerDraft>>({ deliveryId: null, value: EMPTY_DRAFT });
  const [skipConfirmFor, setSkipConfirmFor] = useState<string | null>(null);
  const [finishedDelivery, setFinishedDelivery] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);
  const commentRef = useRef<HTMLInputElement>(null);
  const slotGroupRef = useRef<HTMLDivElement>(null);
  // 同じtick内の二重クリック・キー連打でPOSTが二度出ないよう、送信中のdeliveryを同期的に保持する。
  const inFlightRef = useRef<string | null>(null);
  const deliveryId = deck?.status === "active" ? deck.delivery_id : null;
  const comparison = deliveryId && deck ? { delivery_id: deliveryId, audio: deck.audio } : null;
  const player = useComparisonPlayer(comparison);
  const draft = draftState.deliveryId === deliveryId ? draftState.value : EMPTY_DRAFT;
  const skipConfirm = deliveryId !== null && skipConfirmFor === deliveryId;
  const setDraft = useCallback((next: AnswerDraft | ((value: AnswerDraft) => AnswerDraft)) => {
    setDraftState((state) => {
      const base = state.deliveryId === deliveryId ? state.value : EMPTY_DRAFT;
      return { deliveryId, value: typeof next === "function" ? next(base) : next };
    });
  }, [deliveryId]);

  const loadDeck = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const value = await api<Deck>("/api/deck/active");
      // 同じ比較の再取得(reveal・再開)では音声URLだけが新しく発行される。再生を初めからやり直さない。
      setDeck((previous) => previous && value.delivery_id !== null && previous.delivery_id === value.delivery_id ? { ...value, audio: previous.audio } : value);
      return value;
    } catch (caught) {
      setLoadError(caught);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void loadDeck(); }, [loadDeck]);

  const answer = useMutation({
    mutationFn: ({ deliveryId: id, request }: { deliveryId: string; request: Judgment }) => api<Action>(`/api/deliveries/${id}/judgments`, { method: "POST", body: JSON.stringify(request) }),
    onSuccess: (accepted, variables) => {
      setFinishedDelivery(variables.deliveryId);
      player.pause();
      void queryClient.invalidateQueries({ queryKey: ["project"] });
      if (accepted.result === "ended" && deck?.session_id) setCompletedSessionId(deck.session_id);
      else void loadDeck();
    },
    onError: (_caught, variables) => {
      if (inFlightRef.current === variables.deliveryId) inFlightRef.current = null;
    },
  });
  const lifecycle = useMutation({
    mutationFn: (path: string) => api<Action>(path, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
  const skip = useMutation({
    mutationFn: ({ deliveryId: id, confirmed }: { deliveryId: string; confirmed: boolean }) => api<Action>(`/api/deliveries/${id}/skip`, { method: "POST", body: JSON.stringify({ confirmed }) }),
    onSuccess: async (_accepted, variables) => {
      setFinishedDelivery(variables.deliveryId);
      setSkipConfirmFor(null);
      player.pause();
      await queryClient.invalidateQueries({ queryKey: ["project"] });
      const sessionId = deck?.session_id;
      const next = await loadDeck();
      if (sessionId && next?.session_id === null) setCompletedSessionId(sessionId);
    },
    onError: (caught, variables) => {
      if (inFlightRef.current === variables.deliveryId) inFlightRef.current = null;
      if (!variables.confirmed && isSkipConfirmationRequired(caught)) setSkipConfirmFor(variables.deliveryId);
    },
  });
  const reveal = useMutation({
    mutationFn: (sessionId: string) => api<Action>(`/api/sessions/${sessionId}/reveal`, { method: "POST" }),
    onSuccess: () => void loadDeck(),
  });

  // 新しい比較: 前の比較のエラー表示を消し、フォーカスをA/Bへ移す(送信ボタン等が消えてbodyへ落ちないように)。
  const { reset: resetAnswer } = answer;
  const { reset: resetSkip } = skip;
  const { reset: resetReveal } = reveal;
  useEffect(() => {
    resetAnswer();
    resetSkip();
    resetReveal();
    setActionError(null);
    if (deliveryId !== null) slotGroupRef.current?.focus({ preventScroll: true });
  }, [deliveryId, resetAnswer, resetSkip, resetReveal]);

  const busy = answer.isPending || skip.isPending || finishedDelivery === deliveryId;
  const heardBoth = player.heard.a && player.heard.b;
  const canAnswer = deliveryId !== null && heardBoth && !player.loading && player.error === null && !busy;
  const canSubmit = canAnswer && draft.preference !== null;
  const canSkip = deliveryId !== null && !busy;
  const submit = useCallback(() => {
    if (!deliveryId || !canSubmit || inFlightRef.current === deliveryId) return;
    const request = buildRequest(draft, player.snapshotTelemetry);
    if (!request) return;
    inFlightRef.current = deliveryId;
    answer.mutate({ deliveryId, request });
  }, [answer, canSubmit, deliveryId, draft, player.snapshotTelemetry]);
  const requestSkip = useCallback((confirmed: boolean) => {
    if (!deliveryId || !canSkip || inFlightRef.current === deliveryId) return;
    inFlightRef.current = deliveryId;
    skip.mutate({ deliveryId, confirmed });
  }, [canSkip, deliveryId, skip]);
  const leave = useCallback(() => {
    player.pause();
    setActionError(null);
    if (!deck?.session_id || deck.status !== "active") {
      onBack();
      return;
    }
    lifecycle.mutate(`/api/sessions/${deck.session_id}/pause`, {
      onSuccess: onBack,
      onError: (caught) => setActionError(humanError(caught)),
    });
  }, [deck?.session_id, deck?.status, lifecycle, onBack, player.pause]);
  const resume = useCallback(() => {
    if (!deck?.session_id) return;
    setActionError(null);
    lifecycle.mutate(`/api/sessions/${deck.session_id}/resume`, {
      onSuccess: () => void loadDeck(),
      onError: (caught) => setActionError(humanError(caught)),
    });
  }, [deck?.session_id, lifecycle, loadDeck]);

  const answering = completedSessionId === null && !loading && loadError === null && deliveryId !== null;
  const shortcuts = useMemo(() => ({
    enabled: answering && !skipConfirm,
    canAnswer,
    canSkip,
    canSubmit,
    preference: draft.preference,
    onToggleHelp: () => setShowHelp((value) => !value),
    onSkip: () => requestSkip(false),
    onSwitchSlot: () => void player.switchSlot(),
    onPreference: (preference: 1 | 2 | 3 | 4 | 5) => setDraft((value) => ({ ...value, preference })),
    onToggleBlocker: (slot: "a" | "b") => setDraft((value) => { const key = slot === "a" ? "blockerA" : "blockerB"; return { ...value, [key]: { selected: !value[key].selected, note: "" } }; }),
    onFocusComment: () => commentRef.current?.focus(),
    onSubmit: submit,
  }), [answering, canAnswer, canSkip, canSubmit, draft.preference, player.switchSlot, requestSkip, setDraft, skipConfirm, submit]);
  useDeckShortcuts(shortcuts);

  if (completedSessionId) {
    return <SessionSummary sessionId={completedSessionId} onBack={onBack} onNext={() => { setCompletedSessionId(null); void loadDeck(); }} />;
  }
  if (loading && !deck) return <main className="centered">Deckを準備しています…</main>;
  if (loadError !== null) {
    return (
      <main className="centered error-panel">
        <h1>{isNetworkError(loadError) ? "サーバーに接続できません" : "比較を読み込めません"}</h1>
        <p>{humanError(loadError)}</p>
        <div className="centered-actions">
          <button type="button" className="nibi-button secondary-action" onClick={() => void loadDeck()}>再試行</button>
          <button type="button" className="nibi-button nibi-button--quiet weak-action" onClick={onBack}>受信箱へ</button>
        </div>
      </main>
    );
  }
  if (!deck || !deck.session_id) {
    return (
      <main className="centered error-panel">
        <h1>進行中のセッションはありません</h1>
        <p>受信箱から次のセッションを始めてください。</p>
        <div className="centered-actions">
          <button type="button" className="nibi-button secondary-action" onClick={onBack}>受信箱へ</button>
        </div>
      </main>
    );
  }
  if (deck.status === "paused") {
    return (
      <>
        <PausedPanel pending={lifecycle.isPending} onResume={resume} onBack={onBack} />
        {actionError && <p className="inline-error centered-action-error" role="alert">{actionError}</p>}
      </>
    );
  }
  if (!deliveryId) return <main className="centered">次の比較を準備しています…</main>;

  const answerError = answer.isError && answer.variables.deliveryId === deliveryId ? humanError(answer.error) : null;
  const skipError = skip.isError && skip.variables.deliveryId === deliveryId && !skipConfirm ? humanError(skip.error) : null;
  const revealError = reveal.isError ? humanError(reveal.error) : null;
  return (
    <div className="docked-screen">
      <main className="screen deck-shell">
        <div className="deck-top">
          <DeckHeader deck={deck} onLeave={leave} />
          {actionError && <p className="inline-error" role="alert">{actionError}</p>}
          {skipError && <p className="inline-error" role="alert">{skipError}</p>}
          {revealError && <p className="inline-error" role="alert">{revealError}</p>}
          {showHelp && <aside className="nibi-card shortcut-help" aria-label="キーボード操作">Space A/B切替 · 1〜5 選好 · A/B 問題の指摘 · N メモ · Enter 記録 · 0 飛ばす · ? この一覧（ボタンにフォーカスがあるときの Space・Enter はそのボタンを押します）</aside>}
        </div>
        <ListeningPanel
          player={player}
          deck={deck}
          groupRef={slotGroupRef}
          revealing={reveal.isPending}
          onReveal={() => { if (deck.session_id) reveal.mutate(deck.session_id); }}
        />
        <div className="deck-answer">
          <AnswerEditor
            question={deck.question ?? "どちらを残しますか？"}
            locked={!canAnswer}
            draft={draft}
            commentRef={commentRef}
            error={answerError}
            onChange={setDraft}
          />
        </div>
      </main>
      <AnswerDock
        revealed={draft.preference !== null}
        canSubmit={canSubmit}
        pending={answer.isPending}
        skippable={canSkip}
        skipping={skip.isPending}
        confirm={skipConfirm ? (
          <SkipConfirmBar
            deck={deck}
            pending={skip.isPending}
            onConfirm={() => requestSkip(true)}
            onCancel={() => { if (skip.isPending) return; setSkipConfirmFor(null); skip.reset(); }}
          />
        ) : null}
        onSubmit={submit}
        onSkip={() => requestSkip(false)}
      />
    </div>
  );
}
