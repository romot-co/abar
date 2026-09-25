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
        <button type="button" className="nibi-button nibi-button--link weak-action" onClick={onBack}>受信箱へ</button>
      </div>
    </main>
  );
}

/* ヘッダーは戻る操作と「n / N」だけ(Recipeと進みの棒は出さない、§2.13)。観点は題名の大きさで。 */
export function DeckHeader({ deck, onLeave }: { deck: Deck; onLeave: () => void }) {
  const total = deck.comparison_count;
  const index = deck.sequence_index ?? 0;
  return (
    <>
      <header className="deck-header">
        <button type="button" className="nibi-button nibi-button--link weak-action back-action" onClick={onLeave}><Icon name="chevron_left" />受信箱</button>
        <span className="nibi-value deck-progress" aria-label={`比較 ${index + 1} / ${total}`}>{index + 1} / {total}</span>
      </header>
      {deck.criterion_text && <h1 className="nibi-title deck-criterion">{deck.criterion_text}</h1>}
    </>
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
      <strong id="skip-confirm-title" className="nibi-heading">この比較を飛ばしますか</strong>
      <p id="skip-confirm-message" className="nibi-body">{message}</p>
      <span className="pair-actions confirm-actions">
        <button ref={cancelRef} type="button" className="nibi-button secondary-action" disabled={pending} onClick={onCancel}>続ける</button>
        <button type="button" className="nibi-button secondary-action" disabled={pending} onClick={onConfirm}>{pending ? "飛ばしています…" : "飛ばす"}</button>
      </span>
    </div>
  );
}

/* A/Bのカードを押すとその側を再生し、再生中のカードをもう一度押すと一時停止する(§2.13)。
   再生の状態は印と語で(‖ 再生中 / ▶ 停止中)、聴いたかどうかは別の場所に小さく(✓ 聴いた、未聴取は何も出さない)。
   どちらもまだ聴いていない間だけ「押して聴く」。今聴いている側は主題の選択なので反転する(nibi 0005)。 */
export function ListeningPanel({ player, deck, groupRef, revealing, onReveal }: { player: ComparisonPlayer; deck: Deck; groupRef: RefObject<HTMLDivElement | null>; revealing: boolean; onReveal: () => void }) {
  const identity = deck.identity_by_slot;
  const disabled = player.loading || player.error !== null;
  const fresh = !player.heard.a && !player.heard.b;
  const playState = (slot: "a" | "b"): "playing" | "paused" | null => {
    if (player.activeSlot !== slot) return null;
    if (player.playing) return "playing";
    return player.position > 0 ? "paused" : null;
  };
  return (
    <section className="listen-panel" aria-label="試聴">
      {player.error && <p className="inline-error" role="alert">{player.error}</p>}
      <div ref={groupRef} tabIndex={-1} className="nibi-segmented nibi-segmented--cards slot-switcher" role="group" aria-label={`試聴する音（比較 ${(deck.sequence_index ?? 0) + 1} / ${deck.comparison_count}）。押すと再生、もう一度押すと一時停止`}>
        {(["a", "b"] as const).map((slot) => {
          const active = player.activeSlot === slot;
          const state = playState(slot);
          const heard = player.heard[slot];
          const words = [slot.toUpperCase(), state === "playing" ? "再生中" : state === "paused" ? "停止中" : null, heard ? "聴いた" : "未聴取"].filter(Boolean).join("、");
          return (
            <button
              type="button"
              key={slot}
              disabled={disabled}
              className="nibi-segmented__option"
              aria-pressed={active}
              aria-label={`${words}。${state === "playing" ? "押すと一時停止" : "押すと再生"}`}
              onClick={() => void player.selectSlot(slot)}
            >
              <span className="slot-heard" aria-hidden="true" data-heard={heard ? "" : undefined}>
                {heard && <><Icon name="check" />聴いた</>}
              </span>
              <span className="slot-name">{slot.toUpperCase()}</span>
              {identity?.[slot.toUpperCase()] && <span className="slot-identity">{identityName(identity[slot.toUpperCase()])}</span>}
              <span className="slot-state" aria-hidden="true" data-state={state ?? undefined}>
                {state === "playing" && <><Icon name="pause" />再生中</>}
                {state === "paused" && <><Icon name="play_arrow" />停止中</>}
                {state === null && fresh && !player.playing && "押して聴く"}
              </span>
            </button>
          );
        })}
      </div>
      <div className="transport">
        <input aria-label="再生位置" type="range" min={0} max={Math.max(player.duration, 0.01)} step={0.01} value={player.position} disabled={disabled} onChange={(event) => player.seek(Number(event.currentTarget.value))} />
        <span className="nibi-value time">{formatTime(player.position)} / {formatTime(player.duration)}</span>
      </div>
      {deck.can_reveal && !identity && (
        <p className="reveal-action">
          <button type="button" className="nibi-button nibi-button--link weak-action" disabled={revealing} onClick={onReveal}>A/Bの中身を表示する</button>
        </p>
      )}
    </section>
  );
}

type AnswerEditorProps = {
  question: string;
  locked: boolean;
  heard: { a: boolean; b: boolean };
  draft: AnswerDraft;
  commentRef: RefObject<HTMLInputElement | null>;
  error: string | null;
  canSubmit: boolean;
  pending: boolean;
  onChange: (draft: AnswerDraft) => void;
  onSubmit: () => void;
};

export function AnswerEditor({ question, locked, heard, draft, commentRef, error, canSubmit, pending, onChange, onSubmit }: AnswerEditorProps) {
  const revealed = draft.preference !== null;
  // 押せない間は理由と次の一手を直下に(nibi 0006 / 0007 P-1)。
  const hint = locked
    ? `両方を聴くと選べます · ${!heard.a && !heard.b ? "A と B を押して聴いてください" : heard.a ? "あとは B を聴いてください" : "あとは A を聴いてください"}`
    : revealed ? "" : "どちらかを選ぶと記録できます";
  return (
    <section className="answer-panel" aria-labelledby="preference-title">
      <h2 id="preference-title" className="nibi-heading">{question}</h2>
      <div className="nibi-segmented nibi-segmented--cards nibi-segmented--scale preference-scale" role="radiogroup" aria-label="どちらを残すか" aria-describedby="answer-hint">
        {([1, 2, 3, 4, 5] as const).map((value) => {
          const [side, strength] = preferenceLabel(value);
          return (
            <button
              type="button"
              className="nibi-segmented__option"
              data-neutral={value === 3 ? "" : undefined}
              role="radio"
              aria-label={`${value} ${side ? `${side} が${strength}` : strength}`}
              aria-checked={draft.preference === value}
              disabled={locked}
              key={value}
              onClick={() => onChange({ ...draft, preference: value })}
            >
              {side && <span className="preference-side">{side}</span>}
              <span className="preference-strength">{strength}</span>
            </button>
          );
        })}
      </div>
      <p id="answer-hint" className="nibi-note-text submit-hint" aria-live="polite">{hint}</p>
      <p className="nibi-note-text key-hint">キー 1〜5 でも選べます</p>
      {revealed && (
        <div className="answer-details">
          <fieldset className="blocker-question">
            <legend className="nibi-label">補足（任意）· 残せない問題</legend>
            <div className="blocker-toggles">
              <BlockerToggle slot="A" value={draft.blockerA} disabled={locked} onChange={(blockerA) => onChange({ ...draft, blockerA })} />
              <BlockerToggle slot="B" value={draft.blockerB} disabled={locked} onChange={(blockerB) => onChange({ ...draft, blockerB })} />
            </div>
            <BlockerNote slot="A" value={draft.blockerA} onChange={(blockerA) => onChange({ ...draft, blockerA })} />
            <BlockerNote slot="B" value={draft.blockerB} onChange={(blockerB) => onChange({ ...draft, blockerB })} />
          </fieldset>
          <label className="nibi-field nibi-field--fill comment-field">
            <span className="nibi-field__label">この比較のメモ</span>
            <input
              ref={commentRef}
              className="nibi-field__input"
              maxLength={500}
              placeholder="任意"
              disabled={locked}
              value={draft.comment}
              onChange={(event) => onChange({ ...draft, comment: event.currentTarget.value })}
            />
          </label>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <button type="button" className="nibi-button nibi-button--primary submit-answer" disabled={!canSubmit} onClick={onSubmit}>{pending ? "記録中…" : "記録して次へ"}</button>
        </div>
      )}
      {!revealed && error && <p className="inline-error" role="alert">{error}</p>}
    </section>
  );
}

/* 画面下のdock: 弱い skip のリンクだけ(§2.13)。Plan付きSessionの確認も同じ場所に出す。 */
export function AnswerDock({ skippable, skipping, confirm, onSkip }: { skippable: boolean; skipping: boolean; confirm: ReactNode; onSkip: () => void }) {
  return (
    <div className="nibi-dock answer-dock">
      {confirm ?? (
        <p className="skip-action">
          <button type="button" className="nibi-button nibi-button--link weak-action" disabled={!skippable || skipping} onClick={onSkip}>{skipping ? "飛ばしています…" : "回答せずにこの比較を飛ばす"}</button>
        </p>
      )}
    </div>
  );
}

function BlockerToggle({ slot, value, disabled, onChange }: { slot: "A" | "B"; value: BlockerDraft; disabled: boolean; onChange: (value: BlockerDraft) => void }) {
  return (
    <button
      type="button"
      className="nibi-button nibi-button--toggle blocker-chip"
      aria-pressed={value.selected}
      disabled={disabled}
      onClick={() => onChange({ selected: !value.selected, note: "" })}
    >
      {slot} に問題
    </button>
  );
}

function BlockerNote({ slot, value, onChange }: { slot: "A" | "B"; value: BlockerDraft; onChange: (value: BlockerDraft) => void }) {
  if (!value.selected) return null;
  return (
    <label className="nibi-field nibi-field--fill blocker-note">
      <span className="nibi-field__label">{slot} の問題</span>
      <input
        className="nibi-field__input"
        maxLength={500}
        placeholder="何が残せないか"
        value={value.note}
        onChange={(event) => onChange({ ...value, note: event.currentTarget.value })}
      />
    </label>
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
    ["A", "明確に"],
    ["A", "わずかに"],
    ["", "互角"],
    ["B", "わずかに"],
    ["B", "明確に"],
  ] as const)[value - 1] ?? ["", ""];
}
function formatTime(seconds: number): string { const minutes = Math.floor(seconds / 60); return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`; }
