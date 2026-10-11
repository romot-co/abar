import assert from 'node:assert/strict';
import test from 'node:test';
import { EMPTY_DRAFT, buildRequest, toggleBlocker, changeComment } from '../src/deck/answerDraft.ts';

const loop = { start: 0.2, end: 0.8 };
const measured = () => ({ listenMs: { a: 40, b: 50 }, switches: 1, answerMs: 100, loops: [{ range: loop, listenMs: { a: 40, b: 50 } }] });
test('unanswered cannot submit, held is distinct from tie and carries telemetry', () => {
  assert.equal(buildRequest(EMPTY_DRAFT, measured), null);
  const request = buildRequest({ ...EMPTY_DRAFT, held: true }, measured);
  assert.equal(request.preference, null);
  assert.equal(request.held, true);
  assert.deepEqual(request.telemetry.loops, [{ range: { start_seconds: 0.2, end_seconds: 0.8 }, listen_ms: { a: 40, b: 50 } }]);
  assert.equal(buildRequest({ ...EMPTY_DRAFT, preference: 3 }, measured).held, false);
});
test('blocker stamps at opening, retains the stamp while editing and clears on closing', () => {
  const opened = toggleBlocker(EMPTY_DRAFT.blockerB, loop);
  assert.deepEqual(opened.range, loop);
  const edited = { ...opened, note: 'ミョイン' };
  const request = buildRequest({ ...EMPTY_DRAFT, preference: 3, blockerB: edited }, measured);
  assert.deepEqual(request.blockers.b.range, { start_seconds: 0.2, end_seconds: 0.8 });
  assert.deepEqual(toggleBlocker(edited, { start: 1, end: 2 }), { selected: false, note: '', range: null });
  assert.equal(toggleBlocker(EMPTY_DRAFT.blockerA, null).range, null);
});
test('memo stamps only the first input and clears when emptied', () => {
  const first = changeComment(EMPTY_DRAFT, 'ミ', loop);
  const next = changeComment(first, 'ミョイン', { start: 1, end: 2 });
  assert.deepEqual(next.commentRange, loop);
  assert.deepEqual(changeComment(next, '', null).commentRange, null);
  const plain = changeComment(EMPTY_DRAFT, 'plain', null);
  assert.equal(changeComment(plain, 'plain more', loop).commentRange, null);
});
