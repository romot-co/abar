import assert from 'node:assert/strict';
import test from 'node:test';
import { blockedReason, classifySessions, queueMessage } from '../src/project/inbox.ts';

const card = (id, status, extra = {}) => ({
  project_session_id: id, focus: id, recipe: 'matched-v1', comparison_count: 1, answered_count: 0,
  status, current_best_check: false, completed_at: null, outcome: null, ...extra,
});

test('blocked sessions get their own group, never the completed one', () => {
  const sessions = [card('done', 'done'), card('broken', 'blocked', { outcome: 'Session audio validation failed' }), card('ready', 'ready'), card('active', 'active'), card('closed', 'closed')];
  const { pending, blocked, completed } = classifySessions(sessions);
  assert.deepEqual(pending.map((item) => item.project_session_id), ['active', 'ready']);
  assert.deepEqual(blocked.map((item) => item.project_session_id), ['broken']);
  assert.deepEqual(completed.map((item) => item.project_session_id), ['done']);
});

test('pending sessions are ordered active, paused, ready', () => {
  const { pending } = classifySessions([card('r', 'ready'), card('p', 'paused'), card('a', 'active')]);
  assert.deepEqual(pending.map((item) => item.status), ['active', 'paused', 'ready']);
});

test('"all judged" only when nothing is unanswered, blocked or awaiting confirmation', () => {
  const none = { pendingCount: 0, otherSession: false, blockedCount: 0, confirmationCount: 0 };
  assert.match(queueMessage(none), /^全て判定済みです/);
  assert.equal(queueMessage({ ...none, pendingCount: 1 }), null);
  assert.equal(queueMessage({ ...none, otherSession: true }), null);
  assert.equal(queueMessage({ ...none, confirmationCount: 1 }), null);
  const blockedOnly = queueMessage({ ...none, blockedCount: 1 });
  assert.equal(blockedOnly, '開始できるセッションはありません。');
  assert.doesNotMatch(blockedOnly, /判定済み/);
});

test('the blocked reason is readable words, falling back to the recorded reason', () => {
  assert.match(blockedReason('Session audio validation failed'), /音声を検証できませんでした/);
  assert.equal(blockedReason('renderer exited'), 'renderer exited');
  assert.equal(blockedReason(null), '理由は記録されていません');
});
