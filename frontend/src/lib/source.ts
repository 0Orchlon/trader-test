/**
 * ONE `source` per view (LLD §16.2, AC-21).
 *
 * The backend forbids a mixed source within a single RESPONSE
 * (`MixedSourceError`). On the frontend, a list can carry a source per
 * row, so the guard is needed again here: showing a live row and a
 * backtest row in the same table blurs which one is real.
 */
export function distinctSources(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}
