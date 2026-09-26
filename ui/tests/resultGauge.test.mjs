import assert from 'node:assert/strict';
import test from 'node:test';
import { answerWords, gaugeEnds, orientAnswer, rowGauge, supportChart } from '../src/deck/gauge.ts';
import { conclusion } from '../src/deck/resultCopy.ts';

const variant = (ref, label) => ({ audio_id: `audio_${ref}`, label, provenance: { kind: 'variant', variant_ref: ref } });
const item = (a, b, preference, role = 'evidence') => ({
  audio: [], clip_id: 'clip', delivery_id: `d_${a?.label}_${b?.label}_${preference}`, identity_by_slot: { A: a, B: b },
  judgment: preference === null ? null : { preference, blockers: {}, comment: null }, material_id: 'm', material_name: 'pad.wav',
  role, sequence_index: 0, session_item_id: 'i', skipped: false,
});
const best = variant('v_best', 'warm-eq-v1');
const proposal = variant('v_new', 'dense-chorus-v2');
const planResult = (evidence) => ({
  best_update_evidence: { proposed_variant_id: 'v_new', favorable_count: 0, answered_count: 3, evidence_count: 3, score_sum: -2, blocker_count: 0, ...evidence },
  blockers_by_variant: {}, current_best_updated: false, difference_profile: 'clear', evidence: [], evidence_count: 3,
  // the proposal listed first: the ends must still put the current best on the left
  evidence_direction_counts: { v_new: 0, v_best: 2, tie: 1 }, favored_required_count: 2,
  favored_variant_id: 'v_best', favored_variant_label: 'warm-eq-v1', project_session_id: 'ps', recipe: 'matched-v1',
  repeat_result: 'missing', same_result: 'missing', score_by_variant: {}, variant_labels: { v_new: 'dense-chorus-v2', v_best: 'warm-eq-v1' },
});

test('a plan puts the current best at the start on the left and the proposal on the right', () => {
  const ends = gaugeEnds(planResult({}), []);
  assert.deepEqual([ends.left.label, ends.left.role, ends.right.label, ends.right.role], ['warm-eq-v1', '開始時の現在最良', 'dense-chorus-v2', '提案']);
  assert.equal(ends.bySlot, false);
});

test('the same support draws the same gauge whichever slot the variant was in', () => {
  const ends = gaugeEnds(planResult({}), []);
  // B clearly (5) with the proposal in B, and A clearly (1) with the proposal in A: both support the proposal clearly.
  const bSide = orientAnswer(item(best, proposal, 5), ends, 5);
  const aSide = orientAnswer(item(proposal, best, 1), ends, 1);
  assert.deepEqual(rowGauge(bSide), { side: 'right', blocks: ['clear', 'clear'], word: '明確' });
  assert.deepEqual(rowGauge(aSide), rowGauge(bSide));
  assert.equal(answerWords(aSide, ends), 'dense-chorus-v2 を明確に支持');
  // slightly for the current best when it sat in B
  const slight = orientAnswer(item(proposal, best, 4), ends, 4);
  assert.deepEqual(rowGauge(slight), { side: 'left', blocks: ['slight'], word: 'わずか' });
  assert.equal(answerWords(slight, ends), 'warm-eq-v1 をわずかに支持');
});

test('a tie is a centre dot, a skipped or missing answer draws nothing but still has words', () => {
  const ends = gaugeEnds(planResult({}), []);
  assert.deepEqual(rowGauge(orientAnswer(item(best, proposal, 3), ends, 3)), { side: 'center', blocks: [], word: '互角' });
  assert.deepEqual(rowGauge(orientAnswer(item(best, proposal, null), ends, null), true), { side: null, blocks: [], word: '飛ばした' });
  assert.deepEqual(rowGauge(orientAnswer(item(best, proposal, null), ends, null)), { side: null, blocks: [], word: '未回答' });
});

test('identical sounds have no direction: strength only', () => {
  const ends = gaugeEnds(planResult({}), []);
  const same = { audio_id: 'audio_same', provenance: {} };
  const answer = orientAnswer(item(same, same, 1, 'same'), ends, 1);
  assert.equal(answer.kind, 'symmetric');
  assert.equal(rowGauge(answer).word, '差を報告');
  assert.equal(rowGauge(orientAnswer(item(same, same, 3, 'same'), ends, 3)).word, '互角');
});

test('without result or identities the gauge stays A to B', () => {
  const ends = gaugeEnds(null, [item(undefined, undefined, 2)]);
  assert.equal(ends.bySlot, true);
  assert.equal(rowGauge(orientAnswer(item(undefined, undefined, 2), ends, 2)).side, 'left');
  const quick = gaugeEnds(null, [item(best, proposal, 2)]);
  assert.deepEqual([quick.left.label, quick.right.label], ['warm-eq-v1', 'dense-chorus-v2']);
});

test('support chart: clear blocks nearest the centre, one slot per comparison, ticks at the requirement', () => {
  const directed = (position) => ({ kind: 'directed', position });
  const chart = supportChart([directed(4), directed(3), directed(4), directed(5), directed(1), directed(2), { kind: 'missing' }, directed(5), directed(4)], 6, 9);
  assert.deepEqual(chart.right, ['clear', 'clear', 'slight', 'slight', 'slight']);
  assert.deepEqual(chart.left, ['clear', 'slight']);
  assert.equal(chart.slots, 9);
  assert.ok(Math.abs(chart.threshold - 6 / 9) < 1e-9);
  // the ticks sit the same distance either side of the centre: 50% ∓ (6/9) × 50%
  assert.ok(Math.abs(chart.tickLeft - (0.5 - (6 / 9) * 0.5)) < 1e-9);
  assert.ok(Math.abs(chart.tickRight - (0.5 + (6 / 9) * 0.5)) < 1e-9);
  assert.ok(Math.abs(0.5 - chart.tickLeft - (chart.tickRight - 0.5)) < 1e-9);
});

test('support chart never overflows: a requirement above the count is clamped, empty sessions keep one slot', () => {
  const chart = supportChart([], 3, 0);
  assert.equal(chart.slots, 1);
  assert.equal(chart.threshold, 1);
  assert.deepEqual([chart.tickLeft, chart.tickRight], [0, 1]);
});

const axis = { left: '現在最良', right: '提案' };

test('a kept plan says which condition stopped it, in the order the server checks', () => {
  const ends = gaugeEnds(planResult({}), []);
  assert.deepEqual(conclusion(planResult({}), ends, axis, 'dense-chorus-v2'), {
    headline: '現在最良を維持しました',
    detail: '提案を支持した比較は 3 件中 0 件で、更新に必要な 2 件に届きませんでした。',
  });
  assert.equal(conclusion(planResult({ answered_count: 2, favorable_count: 2, score_sum: 2 }), ends, axis, null).detail, '飛ばした比較があるため、更新の条件を満たしませんでした。');
  assert.equal(conclusion(planResult({ favorable_count: 3, score_sum: 6, blocker_count: 1 }), ends, axis, null).detail, '提案に残せない問題が報告されたため、更新しませんでした。');
  assert.match(conclusion(planResult({ favorable_count: 2, score_sum: 0 }), ends, axis, null).detail, /反対の回答を上回らず/);
});

test('an updated plan names the proposal when its short name fits', () => {
  const updated = { ...planResult({ favorable_count: 3, score_sum: 6 }), current_best_updated: true };
  const ends = gaugeEnds(updated, []);
  assert.equal(conclusion(updated, ends, axis, 'Depth 60').headline, '現在最良を Depth 60 に更新しました');
  assert.equal(conclusion(updated, ends, axis, null).headline, '現在最良を提案に更新しました');
  assert.equal(conclusion(updated, ends, axis, null).detail, '提案を支持した比較は 3 件中 3 件でした（必要 2 件）。');
});

test('an observation separates favoured, all ties, not enough answers, a split and falling short', () => {
  const base = { ...planResult({}), best_update_evidence: null, favored_variant_id: null, favored_variant_label: null, variant_labels: { source: '原音', v_new: 'dense-chorus-v2' } };
  const ends = gaugeEnds(base, []);
  const names = { left: '原音', right: 'chorus' };
  const at = (counts, extra = {}) => conclusion({ ...base, evidence_direction_counts: counts, ...extra }, ends, names, null);
  assert.equal(at({ source: 0, v_new: 3, tie: 0 }, { favored_variant_id: 'v_new' }).headline, 'chorus が優勢でした');
  assert.equal(at({ source: 0, v_new: 0, tie: 3 }).headline, '全比較で互角でした');
  assert.equal(at({ source: 0, v_new: 0, tie: 1 }).headline, '判定できる回答が不足しています');
  assert.equal(at({ source: 1, v_new: 1, tie: 1 }).headline, '判断が素材によって分かれました');
  const short = at({ source: 0, v_new: 1, tie: 2 });
  assert.equal(short.headline, 'chorus の支持が多いが、優勢には届きませんでした');
  assert.equal(short.detail, '優勢には 3 件中 2 件が必要です。現在最良は変わりません。');
  assert.match(at({ source: 0, v_new: 2, tie: 1 }).detail, /強さの合計が正でない/);
});

test('a session outside a Project records only', () => {
  assert.equal(conclusion(null, gaugeEnds(null, []), { left: 'A', right: 'B' }, null).headline, '比較を記録しました');
});
