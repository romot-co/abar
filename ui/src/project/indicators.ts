import type { IndicatorSummaryView } from "../generated";

/*
 * 現在最良の指標の値の書式(§8.2)。値は外部producerの報告のまま(ABARは計算しない、C11)。
 * 同じ単位の値は桁を比べるので、小数の桁数を揃える(0.9 と 0.97 → 0.90 / 0.97)。桁数は単位ごとに、
 * その単位の値が必要とする最大の桁(3 まで)。負号は IBM Plex Sans JP の日本語モードに合わせて U+002D(nibi SPEC §4.5.3)。
 */

const MAX_DECIMALS = 3;

function neededDecimals(value: number): number {
  for (let decimals = 0; decimals < MAX_DECIMALS; decimals += 1) {
    if (Math.abs(Number(value.toFixed(decimals)) - value) < 1e-9) return decimals;
  }
  return MAX_DECIMALS;
}

/** 単位ごとの小数の桁数。 */
export function decimalsByUnit(items: readonly IndicatorSummaryView[]): Map<string, number> {
  const output = new Map<string, number>();
  for (const item of items) {
    if (item.value === null || !Number.isFinite(item.value)) continue;
    output.set(item.unit, Math.max(output.get(item.unit) ?? 0, neededDecimals(item.value)));
  }
  return output;
}

export function formatIndicatorValue(value: number | null, decimals: number): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
}

/** 表示する単位(比 `ratio` は単位を出さない)。 */
export function displayUnit(unit: string): string {
  return unit === "ratio" ? "" : unit;
}
