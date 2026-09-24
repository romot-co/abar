import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import type { Deck } from "../api";
import { Icon } from "../Icon";
import type { ComparisonPlayer } from "../useComparisonPlayer";
import type { AnswerDraft, BlockerDraft } from "./answerDraft";

export function PausedPanel({ pending, onResume, onBack }: { pending: boolean; onResume: () => void; onBack: () => void }) {
  return (
    <main className="centered pause-panel">
      <h1>途中から再開できます</h1>
      <div className="centered-actions">
        <button type="button" className="nibi-button nibi-button--primary primary-action" disabled={pending} onClick={onResume}><Icon name="play_arrow" />再開</button>
        <button type="button" className="nibi-button nibi-button--quiet weak-action" onClick={onBack}>受信箱へ</button>
      </div>
    </main>
  );
}

export function DeckHeader({ deck, onLeave }: { deck: Deck; onLeave: () => void }) {
  const total = deck.comparison_count;
  const index = deck.sequence_index ?? 0;
  return (
    <header className="deck-header">
      <button type="button" className="nibi-button nibi-button--quiet weak-action back-action" onClick={onLeave}><Icon name="chevron_left" />受信箱</button>
      <span className="deck-position">
        <strong className="deck-progress">{index + 1} / {total}</strong>
        {deck.recipe && <span className="deck-recipe">{`Recipe ${deck.recipe}`}</span>}
      </span>
      {deck.criterion_text && (
        <p className="deck-criterion">
          <span>{deck.criterion_label ?? "今回の確認"}</span> {deck.criterion_text}
        </p>
      )}
    </header>
  );
}

export function SkipConfirmBar({ deck, pending, onConfirm, onCancel }: { deck: Deck; pending: boolean; onConfirm: () => void; onCancel: () => void }) {
  // Plan付きSessionでは全比較で確認を求める。どの比較が判定用かは開示しない(§5.1)。
  const message = deck.current_best_check
    ? "回答は記録されません。このセッションは現在最良を更新するかを確かめる比較です。飛ばした比較が判定用だった場合、今回は現在最良が更新されません。"
    : "回答は記録されず、次の比較へ進みます。";
  const cancelRef = useRef<HTMLButtonElement>(null);
  const cancel = useRef(onCancel);
  useEffect(() => { cancel.current = onCancel; }, [onCancel]);
  useEffect(() => {
    const returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancel.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (returnTo?.isConnected) returnTo.focus();
    };
  }, []);
  return (
    <div role="alertdialog" aria-modal="false" aria-labelledby="skip-confirm-title" aria-describedby="skip-confirm-message" className="nibi-card confirm-bar">
      <strong id="skip-confirm-title" className="visually-hidden">この比較を飛ばしますか</strong>
      <p id="skip-confirm-message">{message}</p>
      <span className="pair-actions confirm-actions">
        <button ref={cancelRef} type="button" className="nibi-button secondary-action" disabled={pending} onClick={onCancel}>続ける</button>
        <button type="button" className="nibi-button secondary-action" disabled={pending} onClick={onConfirm}>{pending ? "飛ばしています…" : "飛ばす"}</button>
      </span>
    </div>
  );
}

export function ListeningPanel({ player, deck, groupRef, revealing, onReveal }: { player: ComparisonPlayer; deck: Deck; groupRef: RefObject<HTMLDivElement | null>; revealing: boolean; onReveal: () => void }) {
  const identity = deck.identity_by_slot;
  const disabled = player.loading || player.error !== null;
  const slotState = (slot: "a" | "b"): { label: string; state: "playing" | "heard" | "unheard" } => {
    if (player.activeSlot === slot && player.playing) return { label: "再生中", state: "playing" };
    if (!player.heard[slot]) return { label: "未聴取", state: "unheard" };
    return { label: "聴取済", state: "heard" };
  };
  return (
    <section className="listen-panel" aria-label="試聴">
      {player.error && <p className="inline-error" role="alert">{player.error}</p>}
      <div ref={groupRef} tabIndex={-1} className="nibi-segmented nibi-segmented--cards slot-switcher" role="group" aria-label={`試聴する音（比較 ${(deck.sequence_index ?? 0) + 1} / ${deck.comparison_count}）`}>
        {(["a", "b"] as const).map((slot) => {
          const state = slotState(slot);
          return (
            <button
              type="button"
              key={slot}
              disabled={disabled}
              className="nibi-segmented__option"
              aria-pressed={player.activeSlot === slot}
              onClick={() => void player.selectSlot(slot)}
            >
              <span className="slot-name">{slot.toUpperCase()}</span>
              {identity?.[slot.toUpperCase()] && <span className="slot-identity">{identityName(identity[slot.toUpperCase()])}</span>}
              <span className={`slot-state ${state.state}`}>
                {state.state === "playing" && <span className="state-dot" aria-hidden="true" />}
                {state.state === "heard" && <Icon name="check" />}
                {state.label}
              </span>
            </button>
          );
        })}
      </div>
      <div className="transport">
        <button type="button" className="nibi-button nibi-button--disc play-button" disabled={disabled} onClick={() => player.playing ? player.pause() : void player.play()}>
          <Icon name={player.playing ? "pause" : "play_arrow"} />
          <span className="visually-hidden">{player.playing ? "一時停止" : "再生"}</span>
        </button>
        <input aria-label="再生位置" type="range" min={0} max={Math.max(player.duration, 0.01)} step={0.01} value={player.position} onChange={(event) => player.seek(Number(event.currentTarget.value))} />
        <span className="time">{formatTime(player.position)} / {formatTime(player.duration)}</span>
      </div>
      {deck.can_reveal && !identity && (
        <p className="reveal-action">
          <button type="button" className="nibi-button nibi-button--quiet weak-action" disabled={revealing} onClick={onReveal}>A/Bの中身を表示する</button>
        </p>
      )}
    </section>
  );
}

type AnswerEditorProps = {
  question: string;
  locked: boolean;
  draft: AnswerDraft;
  commentRef: RefObject<HTMLInputElement | null>;
  error: string | null;
  onChange: (draft: AnswerDraft) => void;
};

export function AnswerEditor({ question, locked, draft, commentRef, error, onChange }: AnswerEditorProps) {
  const revealed = draft.preference !== null;
  return (
    <section className="answer-panel" aria-labelledby="preference-title">
      <h2 id="preference-title">{question}</h2>
      {!revealed && (
        <p className="submit-hint" aria-live="polite">
          {locked ? "両方を聴くと回答できます" : "どちらかを選ぶと記録できます"}
        </p>
      )}
      <div className="nibi-segmented nibi-segmented--cards preference-scale" role="radiogroup" aria-label="どちらを残すか">
        {([1, 2, 3, 4, 5] as const).map((value) => {
          const [strength, side] = preferenceLabel(value);
          return (
            <button
              type="button"
              className="nibi-segmented__option"
              data-neutral={value === 3 ? "" : undefined}
              role="radio"
              aria-label={`${value} ${strength}${side}`}
              aria-checked={draft.preference === value}
              disabled={locked}
              key={value}
              onClick={() => onChange({ ...draft, preference: value })}
            >
              {side ? (
                <>
                  <span className="preference-side">{side}</span>
                  <span className="preference-strength">{strength}</span>
                </>
              ) : (
                <span className="preference-side">{strength}</span>
              )}
            </button>
          );
        })}
      </div>
      <p className="key-hint">キー 1〜5 でも選べます</p>
      {revealed && (
        <div className="nibi-card answer-details">
          <div className="blocker-question" role="group" aria-labelledby="blocker-title">
            <p id="blocker-title">残せない問題がありますか？</p>
            <div className="blocker-columns">
              <BlockerColumn slot="A" value={draft.blockerA} disabled={locked} onChange={(blockerA) => onChange({ ...draft, blockerA })} />
              <BlockerColumn slot="B" value={draft.blockerB} disabled={locked} onChange={(blockerB) => onChange({ ...draft, blockerB })} />
            </div>
          </div>
          <input
            ref={commentRef}
            className="comment-field"
            aria-label="この比較のメモ"
            maxLength={500}
            placeholder="この比較のメモ（任意）"
            disabled={locked}
            value={draft.comment}
            onChange={(event) => onChange({ ...draft, comment: event.currentTarget.value })}
          />
        </div>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </section>
  );
}

/* 回答カードの末尾(§2.13)。画面下に留め、記録は選好を決めた後だけ、skipはその下の弱いリンク。
   Plan付きSessionのskip確認も同じ場所に出す(押した場所から目を離さずに確かめられる)。 */
export function AnswerDock({ revealed, canSubmit, pending, skippable, skipping, confirm, onSubmit, onSkip }: {
  revealed: boolean;
  canSubmit: boolean;
  pending: boolean;
  skippable: boolean;
  skipping: boolean;
  confirm: ReactNode;
  onSubmit: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="nibi-dock answer-dock">
      {confirm ?? (
        <>
          {revealed && (
            <button type="button" className="nibi-button nibi-button--primary submit-answer" disabled={!canSubmit} onClick={onSubmit}>{pending ? "記録中…" : "記録して次へ"}</button>
          )}
          <p className="skip-action">
            <button type="button" className="nibi-button nibi-button--quiet weak-action" disabled={!skippable || skipping} onClick={onSkip}>{skipping ? "飛ばしています…" : "回答せずにこの比較を飛ばす"}</button>
          </p>
        </>
      )}
    </div>
  );
}

function BlockerColumn({ slot, value, disabled, onChange }: { slot: "A" | "B"; value: BlockerDraft; disabled: boolean; onChange: (value: BlockerDraft) => void }) {
  return (
    <div className="blocker-column">
      <button
        type="button"
        className="nibi-button nibi-button--toggle blocker-chip"
        aria-pressed={value.selected}
        disabled={disabled}
        onClick={() => onChange({ selected: !value.selected, note: "" })}
      >
        {slot}に問題
      </button>
      {value.selected && (
        <input
          aria-label={`${slot}の問題`}
          maxLength={500}
          placeholder={`${slot} の何が残せないか`}
          value={value.note}
          onChange={(event) => onChange({ ...value, note: event.currentTarget.value })}
        />
      )}
    </div>
  );
}

function identityName(value: NonNullable<Deck["identity_by_slot"]>[string] | undefined): string {
  if (!value) return "";
  if (value.label) return value.label;
  const provenance = value.provenance as Record<string, unknown>;
  return String(provenance.variant_ref ?? provenance.name ?? value.audio_id);
}

function preferenceLabel(value: number): readonly [string, string] {
  return ([
    ["明確に", "A"],
    ["わずかに", "A"],
    ["互角", ""],
    ["わずかに", "B"],
    ["明確に", "B"],
  ] as const)[value - 1] ?? ["", ""];
}
function formatTime(seconds: number): string { const minutes = Math.floor(seconds / 60); return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`; }
