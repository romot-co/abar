import assert from 'node:assert/strict';
import test from 'node:test';
import { blockedReason, classifySessions, leadCopy, queueMessage, selectLead } from '../src/project/inbox.ts';

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

test('history is newest first', () => {
  const { completed } = classifySessions([
    card('old', 'done', { completed_at: '2026-09-24T10:00:00Z' }),
    card('new', 'done', { completed_at: '2026-09-26T10:00:00Z' }),
    card('mid', 'done', { completed_at: '2026-09-25T10:00:00Z' }),
  ]);
  assert.deepEqual(completed.map((item) => item.project_session_id), ['new', 'mid', 'old']);
});

test('the lead is the session in progress, else the first ready one; the rest keep their order', () => {
  const { pending } = classifySessions([card('r1', 'ready'), card('p', 'paused'), card('r2', 'ready')]);
  const { lead, rest } = selectLead(pending, null);
  assert.equal(lead.session.project_session_id, 'p');
  assert.deepEqual(rest.map((item) => item.project_session_id), ['r1', 'r2']);
  const ready = selectLead(classifySessions([card('r1', 'ready'), card('r2', 'ready')]).pending, null);
  assert.equal(ready.lead.session.project_session_id, 'r1');
  assert.deepEqual(ready.rest.map((item) => item.project_session_id), ['r2']);
  assert.deepEqual(selectLead([], null), { lead: null, rest: [] });
});

test('a session outside the Project in progress takes the lead; every Project session stays in the queue', () => {
  const other = { sessionId: 's', status: 'paused' };
  const { lead, rest } = selectLead([card('r1', 'ready')], other);
  assert.deepEqual(lead, { kind: 'other', session: other });
  assert.deepEqual(rest.map((item) => item.project_session_id), ['r1']);
});

test('lead words: continue from the next comparison, or start listening', () => {
  assert.deepEqual(leadCopy({ kind: 'project', session: card('a', 'active', { answered_count: 4, comparison_count: 10 }) }), {
    heading: '途中の試聴', action: '続きから（5 / 10）', step: { current: 5, total: 10 },
  });
  assert.equal(leadCopy({ kind: 'project', session: card('p', 'paused', { answered_count: 10, comparison_count: 10 }) }).action, '続きから（10 / 10）');
  assert.deepEqual(leadCopy({ kind: 'project', session: card('r', 'ready') }), { heading: '次に聴く', action: '聴きはじめる', step: null });
  assert.equal(leadCopy({ kind: 'other', session: { sessionId: 's', status: 'active' } }).heading, '途中の試聴');
});
