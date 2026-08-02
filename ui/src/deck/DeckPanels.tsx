import type { RefObject } from "react";
import type { Deck } from "../api";
import { Icon } from "../Icon";
import type { ComparisonPlayer } from "../useComparisonPlayer";
import type { AnswerDraft, BlockerDraft } from "./answerDraft";

export function PausedPanel({ pending, onResume, onBack }: { pending: boolean; onResume: () => void; onBack: () => void }) {
  return (
    <main className="centered pause-panel">
      <h1>途中から再開できます</h1>
      <button type="button" className="primary-action" disabled={pending} onClick={onResume}><Icon name="play_arrow" />再開</button>
      <button type="button" className="weak-action" onClick={onBack}>受信箱へ</button>
    </main>
  );
}

export function DeckHeader({ deck, onLeave }: { deck: Deck; onLeave: () => void }) {
  const total = deck.comparison_count;
  const index = deck.sequence_index ?? 0;
  return (
    <header className="deck-header">
      <button type="button" className="weak-action" onClick={onLeave}><Icon name="arrow_back" />受信箱</button>
      <strong className="deck-progress">{index + 1} / {total}</strong>
      <span className="deck-recipe">{deck.recipe ? `Recipe ${deck.recipe}` : ""}</span>
    </header>
  );
}

export function SkipConfirmBar({ deck, pending, onConfirm, onCancel }: { deck: Deck; pending: boolean; onConfirm: () => void; onCancel: () => void }) {
  const message = deck.current_best_check
    ? `回答は記録されません。この比較は現在最良を判断する証拠${deck.comparison_count}件の1つで、飛ばすと支持が集まらず更新が成立しにくくなります。`
    : "回答は記録されず、次の比較へ進みます。";
  return (
    <dialog open className="confirm-bar" aria-label="skipの確認">
      <span>{message}</span>
      <span className="confirm-actions">
        <button type="button" className="primary-action" disabled={pending} onClick={onConfirm}>飛ばす</button>
        <button type="button" className="weak-action" disabled={pending} onClick={onCancel}>続ける</button>
      </span>
    </dialog>
  );
}

export function ListeningPanel({ player }: { player: ComparisonPlayer }) {
  const disabled = player.loading || player.error !== null;
  const slotState = (slot: "a" | "b"): { label: string; state: "playing" | "heard" | "unheard" } => {
    if (player.activeSlot === slot && player.playing) return { label: "再生中", state: "playing" };
    if (!player.heard[slot]) return { label: "未聴取", state: "unheard" };
    return { label: "聴取済", state: "heard" };
  };
  return (
    <section className="listen-panel" aria-label="試聴">
      {player.error && <p className="inline-error">{player.error}</p>}
      <div className="slot-switcher" role="group" aria-label="試聴する音">
        {(["a", "b"] as const).map((slot) => {
          const state = slotState(slot);
          return (
            <button
              type="button"
              key={slot}
              disabled={disabled}
              className={player.activeSlot === slot ? "selected" : ""}
              aria-pressed={player.activeSlot === slot}
              onClick={() => void player.selectSlot(slot)}
            >
              <span className="slot-name">{slot.toUpperCase()}</span>
              <span className={`slot-state ${state.state}`}>
                {state.state === "playing" && <span className="state-dot" aria-hidden="true" />}
                {state.label}
              </span>
            </button>
          );
        })}
      </div>
      <div className="transport">
        <button type="button" className="play-button" disabled={disabled} onClick={() => player.playing ? player.pause() : void player.play()}>
          <Icon name={player.playing ? "pause" : "play_arrow"} />
          <span className="visually-hidden">{player.playing ? "Pause" : "Play"}</span>
        </button>
        <input aria-label="再生位置" type="range" min={0} max={Math.max(player.duration, 0.01)} step={0.01} value={player.position} onChange={(event) => player.seek(Number(event.currentTarget.value))} />
        <span className="time">{formatTime(player.position)} / {formatTime(player.duration)}</span>
      </div>
    </section>
  );
}

type AnswerEditorProps = {
  question: string;
  locked: boolean;
  draft: AnswerDraft;
  commentRef: RefObject<HTMLInputElement | null>;
  pending: boolean;
  error: string | null;
  canSubmit: boolean;
  skipping: boolean;
  onChange: (draft: AnswerDraft) => void;
  onSubmit: () => void;
  onSkip: () => void;
};

export function AnswerEditor({ question, locked, draft, commentRef, pending, error, canSubmit, skipping, onChange, onSubmit, onSkip }: AnswerEditorProps) {
  const revealed = draft.preference !== null;
  return (
    <section className="answer-panel" aria-labelledby="preference-title">
      <h2 id="preference-title">{question}</h2>
      <div className="preference-scale" role="radiogroup" aria-label="どちらを残すか">
        {([1, 2, 3, 4, 5] as const).map((value) => {
          const label = preferenceLabel(value);
          return (
            <button
              type="button"
              className={draft.preference === value ? "selected" : ""}
              role="radio"
              aria-label={`${value} ${label.join("")}`}
              aria-checked={draft.preference === value}
              disabled={locked}
              key={value}
              onClick={() => onChange({ ...draft, preference: value })}
            >
              <span>{label[0]}{label[1] && <><br />{label[1]}</>}</span>
            </button>
          );
        })}
      </div>
      <p className="key-hint">キー 1〜5 でも選べます</p>
      {!revealed && (
        <p className="submit-hint" aria-live="polite">
          {locked ? "両方を聴くと回答できます" : "どちらかを選ぶと記録できます"}
        </p>
      )}
      {revealed && (
        <div className="answer-details">
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
          {error && <p className="inline-error">{error}</p>}
        </div>
      )}
      {revealed && (
        <button type="button" className="submit-answer" disabled={!canSubmit} onClick={onSubmit}>{pending ? "記録中…" : "記録して次へ"}</button>
      )}
      <p className="skip-action">
        <button type="button" className="weak-action" disabled={skipping} onClick={onSkip}>回答せずにこの比較を飛ばす</button>
      </p>
    </section>
  );
}

function BlockerColumn({ slot, value, disabled, onChange }: { slot: "A" | "B"; value: BlockerDraft; disabled: boolean; onChange: (value: BlockerDraft) => void }) {
  return (
    <div className="blocker-column">
      <button
        type="button"
        className={value.selected ? "blocker-chip selected" : "blocker-chip"}
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
