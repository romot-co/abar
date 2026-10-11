import type { Judgment } from "../api";
import type { LoopRange } from "./loopRange";
import type { PlayerTelemetry } from "../useComparisonPlayer";

export type BlockerDraft = { selected: boolean; note: string; range: LoopRange | null };
export type AnswerDraft = {
  preference: 1 | 2 | 3 | 4 | 5 | null;
  blockerA: BlockerDraft;
  blockerB: BlockerDraft;
  comment: string;
  held: boolean;
  commentRange: LoopRange | null;
};
export const EMPTY_DRAFT: AnswerDraft = {
  preference: null,
  blockerA: { selected: false, note: "", range: null },
  blockerB: { selected: false, note: "", range: null },
  comment: "",
  held: false,
  commentRange: null,
};

export function buildRequest(draft: AnswerDraft, telemetry: () => PlayerTelemetry): Judgment | null {
  if (draft.preference === null && !draft.held) return null;
  const measured = telemetry();
  return {
    preference: draft.held ? null : draft.preference,
    held: draft.held,
    comment_range: wireRange(draft.commentRange),
    blockers: {
      a: { selected: draft.blockerA.selected, note: draft.blockerA.selected && draft.blockerA.note ? draft.blockerA.note : null, range: wireRange(draft.blockerA.selected ? draft.blockerA.range : null) },
      b: { selected: draft.blockerB.selected, note: draft.blockerB.selected && draft.blockerB.note ? draft.blockerB.note : null, range: wireRange(draft.blockerB.selected ? draft.blockerB.range : null) },
    },
    comment: draft.comment || null,
    telemetry: { listen_ms: measured.listenMs, switches: measured.switches, answer_ms: measured.answerMs, loops: (measured.loops ?? []).map((loop) => ({ range: wireRange(loop.range)!, listen_ms: loop.listenMs })) },
  };
}

function wireRange(range: LoopRange | null) {
  return range ? { start_seconds: range.start, end_seconds: range.end } : null;
}

export function toggleBlocker(value: BlockerDraft, loop: LoopRange | null): BlockerDraft {
  return { selected: !value.selected, note: "", range: value.selected ? null : loop ? { ...loop } : null };
}

export function changeComment(draft: AnswerDraft, comment: string, loop: LoopRange | null): AnswerDraft {
  return { ...draft, comment, commentRange: !comment ? null : draft.comment ? draft.commentRange : loop ? { ...loop } : null };
}

// Match a complete suggestion, so a short word never removes part of another sentence.
function wordPattern(word: string): RegExp {
  return new RegExp(`(^|\\s)${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\s|$)`, "u");
}

export function hasMemoWord(comment: string, word: string): boolean {
  return wordPattern(word).test(comment);
}

export function canToggleMemoWord(comment: string, word: string): boolean {
  const separatorLength = comment && !/\s$/u.test(comment) ? 1 : 0;
  return hasMemoWord(comment, word) || comment.length + separatorLength + word.length <= 500;
}

export function toggleMemoWord(draft: AnswerDraft, word: string, loop: LoopRange | null): AnswerDraft {
  const match = wordPattern(word).exec(draft.comment);
  let comment: string;
  if (match) {
    comment = draft.comment.slice(0, match.index) + draft.comment.slice(match.index + match[0].length);
    if (match.index === 0) comment = comment.trimStart();
    if (!comment.trim()) comment = "";
  } else {
    const separator = draft.comment && !/\s$/u.test(draft.comment) ? " " : "";
    comment = draft.comment + separator + word;
    if (comment.length > 500) return draft;
  }
  return changeComment(draft, comment, loop);
}
