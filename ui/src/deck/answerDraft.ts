import type { Judgment } from "../api";
import type { PlayerTelemetry } from "../useComparisonPlayer";

export type BlockerDraft = { selected: boolean; note: string };
export type AnswerDraft = {
  preference: 1 | 2 | 3 | 4 | 5 | null;
  blockerA: BlockerDraft;
  blockerB: BlockerDraft;
  comment: string;
};
export const EMPTY_DRAFT: AnswerDraft = {
  preference: null,
  blockerA: { selected: false, note: "" },
  blockerB: { selected: false, note: "" },
  comment: "",
};

export function buildRequest(draft: AnswerDraft, telemetry: () => PlayerTelemetry): Judgment | null {
  if (draft.preference === null) return null;
  const measured = telemetry();
  return {
    preference: draft.preference,
    blockers: {
      a: { selected: draft.blockerA.selected, note: draft.blockerA.selected && draft.blockerA.note ? draft.blockerA.note : null },
      b: { selected: draft.blockerB.selected, note: draft.blockerB.selected && draft.blockerB.note ? draft.blockerB.note : null },
    },
    comment: draft.comment || null,
    telemetry: { listen_ms: measured.listenMs, switches: measured.switches, answer_ms: measured.answerMs },
  };
}
