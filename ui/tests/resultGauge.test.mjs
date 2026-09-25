import assert from 'node:assert/strict';
import test from 'node:test';
import { activeCells, answerWords, gaugeEnds, orientAnswer } from '../src/deck/gauge.ts';
import { conditionReason } from '../src/deck/resultCopy.ts';

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
  assert.deepEqual(activeCells(bSide), [4]);
  assert.deepEqual(activeCells(aSide), [4]);
  assert.equal(answerWords(aSide, ends), 'dense-chorus-v2を明確に支持');
  // slightly for the current best when it sat in B
  const slight = orientAnswer(item(proposal, best, 4), ends, 4);
  assert.deepEqual(activeCells(slight), [1]);
  assert.equal(answerWords(slight, ends), 'warm-eq-v1をわずかに支持');
});

test('identical sounds have no direction: strength only, drawn symmetrically', () => {
  const ends = gaugeEnds(planResult({}), []);
  const same = { audio_id: 'audio_same', provenance: {} };
  const answer = orientAnswer(item(same, same, 1, 'same'), ends, 1);
  assert.equal(answer.kind, 'symmetric');
  assert.deepEqual(activeCells(answer), [0, 4]);
  assert.deepEqual(activeCells(orientAnswer(item(same, same, 3, 'same'), ends, 3)), [2]);
  assert.deepEqual(activeCells(orientAnswer(item(best, proposal, null), ends, null)), []);
});

test('without result or identities the gauge stays A to B', () => {
  const ends = gaugeEnds(null, [item(undefined, undefined, 2)]);
  assert.equal(ends.bySlot, true);
  assert.deepEqual(activeCells(orientAnswer(item(undefined, undefined, 2), ends, 2)), [1]);
  const quick = gaugeEnds(null, [item(best, proposal, 2)]);
  assert.deepEqual([quick.left.label, quick.right.label], ['warm-eq-v1', 'dense-chorus-v2']);
});

test('the condition line names counts and the requirement, and keeping is not a failure', () => {
  const kept = conditionReason(planResult({}));
  assert.equal(kept.text, '提案（dense-chorus-v2）を支持: 3件中0件（必要 2件）');
  assert.equal(kept.kind, 'unknown');
  const met = conditionReason({ ...planResult({ favorable_count: 2, score_sum: 3 }), favored_variant_id: 'v_new' });
  assert.equal(met.kind, 'pass');
  const weak = conditionReason(planResult({ favorable_count: 2, score_sum: 0 }));
  assert.match(weak.text, /強さの合計が正でない$/);
  const skipped = conditionReason(planResult({ answered_count: 2, favorable_count: 2, score_sum: 2 }));
  assert.match(skipped.text, /1件は未回答/);
  assert.equal(skipped.kind, 'unknown');
});

test('an observation says who is favoured, or the most support short of the requirement', () => {
  const base = { ...planResult({}), best_update_evidence: null, variant_labels: { source: '原音', v_new: 'dense-chorus-v2' } };
  const short = conditionReason({ ...base, favored_variant_id: null, favored_variant_label: null, evidence_direction_counts: { source: 0, v_new: 1, tie: 2 } });
  assert.equal(short.text, 'どちらも優勢に届かない: 3件中、最多はdense-chorus-v2の1件（必要 2件）');
  assert.equal(short.kind, 'unknown');
  const favoured = conditionReason({ ...base, favored_variant_id: 'v_new', favored_variant_label: 'dense-chorus-v2', evidence_direction_counts: { source: 0, v_new: 3, tie: 0 } });
  assert.equal(favoured.text, 'dense-chorus-v2が優勢: 3件中3件（必要 2件）');
  const none = conditionReason({ ...base, favored_variant_id: null, favored_variant_label: null, evidence_direction_counts: { source: 0, v_new: 0, tie: 3 } });
  assert.match(none.text, /どちらの支持もなし/);
});
