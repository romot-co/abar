import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Action, type Deck, type Judgment } from "../api";
import { humanError, isSkipConfirmationRequired } from "../errors";
import { useComparisonPlayer } from "../useComparisonPlayer";
import { EMPTY_DRAFT, buildRequest, type AnswerDraft } from "./answerDraft";
import { AnswerEditor, DeckHeader, ListeningPanel, PausedPanel, SkipConfirmBar } from "./DeckPanels";
import { SessionSummary } from "./SessionSummary";
import { useDeckShortcuts } from "./useDeckShortcuts";

export function DeckScreen({ onBack }: { onBack: () => void }) {
  const queryClient = useQueryClient();
  const [deck, setDeck] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AnswerDraft>(EMPTY_DRAFT);
  const [showHelp, setShowHelp] = useState(false);
  const [skipConfirm, setSkipConfirm] = useState(false);
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);
  const commentRef = useRef<HTMLInputElement>(null);
  const comparison = deck?.delivery_id ? { delivery_id: deck.delivery_id, audio: deck.audio } : null;
  const player = useComparisonPlayer(comparison);

  const loadDeck = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const value = await api<Deck>("/api/deck/active");
      setDeck(value);
      return value;
    } catch (caught) {
      setError(humanError(caught));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void loadDeck(); }, [loadDeck]);
  useEffect(() => {
    setDraft(EMPTY_DRAFT);
    setSkipConfirm(false);
    setActionError(null);
  }, [deck?.delivery_id]);

  const answer = useMutation({
    mutationFn: ({ deliveryId, request }: { deliveryId: string; request: Judgment }) => api<Action>(`/api/deliveries/${deliveryId}/judgments`, { method: "POST", body: JSON.stringify(request) }),
    onSuccess: (accepted) => {
      player.pause();
      void queryClient.invalidateQueries({ queryKey: ["status"] });
      if (accepted.result === "ended" && deck?.session_id) setCompletedSessionId(deck.session_id);
      else void loadDeck();
    },
  });
  const lifecycle = useMutation({
    mutationFn: (path: string) => api<Action>(path, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["status"] });
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
  const skip = useMutation({
    mutationFn: ({ deliveryId, confirmed }: { deliveryId: string; confirmed: boolean }) => api<Action>(`/api/deliveries/${deliveryId}/skip`, { method: "POST", body: JSON.stringify({ confirmed }) }),
    onSuccess: async () => {
      setSkipConfirm(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["status"] }),
        queryClient.invalidateQueries({ queryKey: ["project"] }),
      ]);
      const sessionId = deck?.session_id;
      const next = await loadDeck();
      if (sessionId && next?.session_id === null) setCompletedSessionId(sessionId);
    },
    onError: (caught, variables) => {
      if (!variables.confirmed && isSkipConfirmationRequired(caught)) setSkipConfirm(true);
    },
  });

  const heardBoth = player.heard.a && player.heard.b;
  const canAnswer = heardBoth && !player.loading && player.error === null;
  const canSubmit = canAnswer && draft.preference !== null && !answer.isPending;
  const submit = useCallback(() => {
    if (!deck?.delivery_id || !canSubmit) return;
    const request = buildRequest(draft, player.snapshotTelemetry);
    if (request) answer.mutate({ deliveryId: deck.delivery_id, request });
  }, [answer, canSubmit, deck?.delivery_id, draft, player.snapshotTelemetry]);
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
  const requestSkip = useCallback(() => {
    if (deck?.delivery_id) skip.mutate({ deliveryId: deck.delivery_id, confirmed: false });
  }, [deck?.delivery_id, skip]);
  const shortcuts = useMemo(() => ({
    deliveryPresent: Boolean(deck?.delivery_id),
    canAnswer,
    canSkip: Boolean(deck?.delivery_id),
    canSubmit,
    preference: draft.preference,
    onToggleHelp: () => setShowHelp((value) => !value),
    onSkip: requestSkip,
    onSwitchSlot: () => void player.switchSlot(),
    onPreference: (preference: 1 | 2 | 3 | 4 | 5) => setDraft((value) => ({ ...value, preference })),
    onToggleBlocker: (slot: "a" | "b") => setDraft((value) => { const key = slot === "a" ? "blockerA" : "blockerB"; return { ...value, [key]: { selected: !value[key].selected, note: "" } }; }),
    onFocusComment: () => commentRef.current?.focus(),
    onSubmit: submit,
  }), [canAnswer, canSubmit, deck?.delivery_id, draft.preference, player.switchSlot, requestSkip, submit]);
  useDeckShortcuts(shortcuts);

  if (completedSessionId) {
    return <SessionSummary sessionId={completedSessionId} onBack={onBack} onNext={() => { setCompletedSessionId(null); void loadDeck(); }} />;
  }
  if (loading) return <main className="centered">Deckを準備しています…</main>;
  if (error || !deck || !deck.session_id) {
    return (
      <main className="centered error-panel">
        <h1>アクティブなSessionがありません</h1>
        <p>{error}</p>
        <button type="button" className="secondary-action" onClick={onBack}>受信箱へ</button>
      </main>
    );
  }
  if (deck.status === "paused") {
    return (
      <>
        <PausedPanel pending={lifecycle.isPending} onResume={resume} onBack={onBack} />
        {actionError && <p className="inline-error centered-action-error">{actionError}</p>}
      </>
    );
  }
  if (!deck.delivery_id) return <main className="centered">次の比較を準備しています…</main>;

  return (
    <main className="deck-shell">
      <div className="deck-top">
        <DeckHeader deck={deck} onLeave={leave} />
        {skipConfirm && (
          <SkipConfirmBar
            deck={deck}
            pending={skip.isPending}
            onConfirm={() => skip.mutate({ deliveryId: deck.delivery_id!, confirmed: true })}
            onCancel={() => { setSkipConfirm(false); skip.reset(); }}
          />
        )}
        {actionError && <p className="inline-error">{actionError}</p>}
        {skip.isError && !skipConfirm && <p className="inline-error">{humanError(skip.error)}</p>}
        {showHelp && <aside className="shortcut-help">Space A/B切替 · 1〜5 選好 · A/B blocker · N メモ · Enter 記録 · 0 skip · ? この一覧</aside>}
      </div>
      <ListeningPanel player={player} />
      <div className="deck-answer">
        <AnswerEditor
          question={deck.question ?? "どちらを残しますか？"}
          locked={!canAnswer}
          draft={draft}
          commentRef={commentRef}
          pending={answer.isPending}
          error={answer.isError ? humanError(answer.error) : null}
          canSubmit={canSubmit}
          skipping={skip.isPending}
          onChange={setDraft}
          onSubmit={submit}
          onSkip={requestSkip}
        />
      </div>
    </main>
  );
}
