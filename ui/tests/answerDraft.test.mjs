import assert from 'node:assert/strict';
import test from 'node:test';
import { EMPTY_DRAFT, buildRequest, toggleBlocker, changeComment, hasMemoWord, canToggleMemoWord, toggleMemoWord } from '../src/deck/answerDraft.ts';

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

test('suggestions toggle memo text, stamp first input and clear the stamp with the last word', () => {
  const first = toggleMemoWord(EMPTY_DRAFT, 'ミョイン', loop);
  assert.equal(first.comment, 'ミョイン');
  assert.deepEqual(first.commentRange, loop);
  const second = toggleMemoWord(first, '尾が揺れる', { start: 1, end: 2 });
  assert.equal(second.comment, 'ミョイン 尾が揺れる');
  assert.deepEqual(second.commentRange, loop);
  const removed = toggleMemoWord(second, 'ミョイン', null);
  assert.equal(removed.comment, '尾が揺れる');
  assert.deepEqual(removed.commentRange, loop);
  const empty = toggleMemoWord(removed, '尾が揺れる', null);
  assert.equal(empty.comment, '');
  assert.equal(empty.commentRange, null);
  const plain = changeComment(EMPTY_DRAFT, '手書きのメモ', null);
  assert.equal(toggleMemoWord(plain, 'ミョイン', loop).commentRange, null);
});

test('suggestion matching preserves sentences, multiword terms and regex punctuation', () => {
  assert.equal(hasMemoWord('尾が揺れる', '尾'), false);
  assert.equal(hasMemoWord('既存 phase (A+B) 続き', 'phase (A+B)'), true);
  const sentence = changeComment(EMPTY_DRAFT, '尾が揺れる', null);
  const added = toggleMemoWord(sentence, '尾', null);
  assert.equal(added.comment, '尾が揺れる 尾');
  assert.equal(toggleMemoWord(added, '尾', null).comment, '尾が揺れる');
  const full = changeComment(EMPTY_DRAFT, 'x'.repeat(500), null);
  assert.equal(canToggleMemoWord(full.comment, '尾'), false);
  assert.equal(canToggleMemoWord('x'.repeat(498) + ' 尾', '尾'), true);
  assert.equal(toggleMemoWord(full, '尾', loop), full);
});
