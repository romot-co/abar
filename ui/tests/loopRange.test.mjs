import assert from 'node:assert/strict';
import test from 'node:test';
import { initialLoop, moveEndpoint, loopPosition, rangeText } from '../src/deck/loopRange.ts';

test('initial range is centered, clamped and handles clips shorter than minimum', () => {
  assert.deepEqual(initialLoop(3, 6), { start: 2.5, end: 3.5 });
  assert.deepEqual(initialLoop(0, 6), { start: 0, end: 1 });
  assert.deepEqual(initialLoop(6, 6), { start: 5, end: 6 });
  assert.deepEqual(initialLoop(0, 0.1), { start: 0, end: 0.1 });
  assert.equal(rangeText({ start: 2.8, end: 3.4 }), '2.80 – 3.40 s');
});
test('handles never cross or leave audio', () => {
  const range = { start: 2, end: 3 };
  assert.deepEqual(moveEndpoint(range, 'start', 4, 6), { start: 2.75, end: 3 });
  assert.deepEqual(moveEndpoint(range, 'end', 0, 6), { start: 2, end: 2.25 });
  assert.equal(moveEndpoint(range, 'end', 99, 6).end, 6);
  assert.equal(moveEndpoint(range, 'start', -99, 6).start, 0);
});
test('logical playhead wraps to loopStart and counts missed animation frames', () => {
  const range = { start: 2, end: 2.25 };
  assert.deepEqual(loopPosition(2, 0.3, 6, range), { position: 2.05, cycle: 1 });
  const several = loopPosition(2, 0.85, 6, range);
  assert.equal(several.cycle, 3);
  assert.ok(Math.abs(several.position - 2.1) < 1e-9);
  assert.deepEqual(loopPosition(1, 6, 6, null), { position: 1, cycle: 1 });
});
