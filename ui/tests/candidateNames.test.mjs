import assert from 'node:assert/strict';
import test from 'node:test';
import { axisNames, shortenPair } from '../src/deck/candidateNames.ts';

const D100 = 'Selected K6 native Depth 100 (F80 GMoff); 20260926';
const D60 = 'Selected K6 native Depth 60 (F80 GMoff); 20260926';

test('same word count: keep only the differing words, with their item name', () => {
  const [left, right] = shortenPair(D100, D60);
  assert.equal(left.short, 'Depth 100');
  assert.equal(right.short, 'Depth 60');
  assert.equal(left.full, D100);
  assert.deepEqual(left.tokens.filter((token) => token.differs).map((token) => token.text), ['100']);
});

test('several differences are joined with a middle dot; units after a value are dropped', () => {
  const [left, right] = shortenPair(
    'Selected K6 native Depth 100 Tilt −2 dB lookahead 12 ms oversampling 4x (F80 GMoff); 20260926',
    'Selected K6 native Depth 60 Tilt −1 dB lookahead 6 ms oversampling 2x (F80 GMoff); 20260926',
  );
  assert.equal(left.short, 'Depth 100 · Tilt −2 · lookahead 12 · oversampling 4x');
  assert.equal(right.short, 'Depth 60 · Tilt −1 · lookahead 6 · oversampling 2x');
});

test('a word with brackets or a semicolon is not an item name', () => {
  const [left, right] = shortenPair('K6 (F80 GMoff); 1', 'K6 (F80 GMoff); 2');
  assert.deepEqual([left.short, right.short], ['1', '2']);
});

test('different word counts: drop the common start and end, never leave a side empty', () => {
  const [left, right] = shortenPair('Depth 60 (F80 GMoff)', 'Depth 60 (F80 GMoff, lookahead 0)');
  assert.equal(left.short, 'GMoff)');
  assert.equal(right.short, 'GMoff, lookahead 0)');
  const [short, long] = shortenPair('Depth 60', 'Depth 60 lookahead 0');
  assert.equal(short.short, 'Depth 60');
  assert.equal(long.short, 'Depth 60 lookahead 0');
});

test('nothing in common, identical, or one-word names stay whole', () => {
  const [v3, other] = shortenPair('v3', 'Selected K7 hybrid Depth 80');
  assert.deepEqual([v3.short, other.short], ['v3', 'Selected K7 hybrid Depth 80']);
  assert.ok(other.tokens.every((token) => token.differs));
  const [same] = shortenPair('warm-eq-v1', 'warm-eq-v1');
  assert.equal(same.short, 'warm-eq-v1');
  const [a, b] = shortenPair('原音', 'dense-chorus-v2');
  assert.deepEqual([a.short, b.short], ['原音', 'dense-chorus-v2']);
});

test('axis names: roles for a plan, short names up to 12 characters, otherwise 候補 1 / 2', () => {
  const [left, right] = shortenPair(D100, D60);
  assert.deepEqual(axisNames(left, right, false), { left: 'Depth 100', right: 'Depth 60', aliased: false });
  assert.deepEqual(axisNames(left, right, true), { left: '現在最良', right: '提案', aliased: false });
  const [longLeft, longRight] = shortenPair('a Depth 100 Tilt −2', 'a Depth 60 Tilt −1');
  assert.deepEqual(axisNames(longLeft, longRight, false), { left: '候補 1', right: '候補 2', aliased: true });
  const [twelve] = shortenPair('(k) 123456789012', '(k) 2');
  assert.equal(twelve.short, '123456789012');
  assert.equal(axisNames(twelve, twelve, false).aliased, false);
});
