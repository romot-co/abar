import assert from 'node:assert/strict';
import test from 'node:test';
import { decimalsByUnit, displayUnit, formatIndicatorValue } from '../src/project/indicators.ts';

const indicator = (value, unit = 'ratio') => ({ id: `i${value}`, label: 'X', description: '', role: 'guard', unit, value, guard_result: null });

test('values of one unit share the decimals they need, so the digits line up', () => {
  const decimals = decimalsByUnit([indicator(0.9), indicator(0.97), indicator(-1.9, 'dB'), indicator(2, 'dB'), indicator(null)]);
  assert.equal(decimals.get('ratio'), 2);
  assert.equal(decimals.get('dB'), 1);
  assert.deepEqual([0.9, 0.97].map((value) => formatIndicatorValue(value, 2)), ['0.90', '0.97']);
  assert.equal(formatIndicatorValue(-1.9, 1), '-1.9');
  assert.equal(formatIndicatorValue(null, 2), '—');
});

test('decimals stop at three and whole numbers need none', () => {
  assert.equal(decimalsByUnit([indicator(1 / 3)]).get('ratio'), 3);
  assert.equal(decimalsByUnit([indicator(12, 'ms')]).get('ms'), 0);
});

test('a ratio has no unit to show', () => {
  assert.equal(displayUnit('ratio'), '');
  assert.equal(displayUnit('dB'), 'dB');
});
