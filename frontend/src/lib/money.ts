/**
 * Money boundary rule — frontend side (AC-25).
 *
 * Fixed-point strings are NEVER coerced through `Number(...)`: a 0.1 + 0.2
 * rounding error wouldn't show on equity, but it would leak into risk
 * calculations. So formatting works ONLY on strings.
 *
 * ESLint bans `Number()` outside this file.
 */

const GROUP = /\B(?=(\d{3})+(?!\d))/g;

export type Money = string;
export type Quantity = string;

export function isNegative(value: Money | null | undefined): boolean {
  return typeof value === 'string' && value.trimStart().startsWith('-');
}

/** `-1234.56` → `-1,234.56`. String in, string out. */
export function formatMoney(value: Money | null | undefined, currency = '$'): string {
  if (value === null || value === undefined || value === '') return '—';
  const negative = isNegative(value);
  const [whole = '0', fraction] = value.replace('-', '').split('.');
  const grouped = whole.replace(GROUP, ',');
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return `${negative ? '−' : ''}${currency}${body}`;
}

/** Quantity — no currency symbol, still grouped. */
export function formatQuantity(value: Quantity | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const negative = isNegative(value);
  const [whole = '0', fraction] = value.replace('-', '').split('.');
  const grouped = whole.replace(GROUP, ',');
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return `${negative ? '−' : ''}${body}`;
}

/**
 * Computed notional = qty × price. Both are strings in, result is a string.
 * Integer arithmetic only — floats never enter this.
 */
export function multiply(qty: Quantity, price: Money): Money | null {
  const left = toScaled(qty);
  const right = toScaled(price);
  if (left === null || right === null) return null;
  const product = left.value * right.value;
  return fromScaled(product, left.scale + right.scale, 2);
}

type Scaled = { value: bigint; scale: number };

function toScaled(text: string): Scaled | null {
  if (!/^-?\d+(\.\d+)?$/.test(text.trim())) return null;
  const [whole = '0', fraction = ''] = text.trim().split('.');
  return { value: BigInt(`${whole}${fraction}`), scale: fraction.length };
}

function fromScaled(value: bigint, scale: number, targetScale: number): string {
  let scaled = value;
  let current = scale;
  while (current > targetScale) {
    // Truncate — not banker's rounding. Notional is a preview estimate,
    // rounding down never overstates it to the operator.
    scaled /= 10n;
    current -= 1;
  }
  while (current < targetScale) {
    scaled *= 10n;
    current += 1;
  }
  const negative = scaled < 0n;
  const digits = (negative ? -scaled : scaled).toString().padStart(targetScale + 1, '0');
  const whole = digits.slice(0, digits.length - targetScale);
  const fraction = digits.slice(digits.length - targetScale);
  return `${negative ? '-' : ''}${whole}.${fraction}`;
}

/** UTC timestamp → `14:30:00Z`. NEVER converted to local timezone (AC-26). */
export function formatUtcTime(value: string | null | undefined): string {
  if (!value) return '—';
  return `${value.slice(11, 19)}Z`;
}

export function formatUtc(value: string | null | undefined): string {
  if (!value) return '—';
  return `${value.slice(0, 10)} ${value.slice(11, 19)}Z`;
}

/**
 * Local-time display (T-99, personal project) — deliberately separate from
 * `formatUtcTime`/`formatUtc` above, which stay UTC-only per AC-26 (a fill
 * or halt timestamp must compare unambiguously against the broker's own
 * UTC-stamped records — DST and viewer-timezone guesswork has no place
 * there). This is for at-a-glance display only; pair it with the raw UTC
 * string as a `title` tooltip wherever exact audit precision matters.
 * Reads the browser's own timezone automatically — no config, no per-user
 * setting, works the same for anyone anywhere.
 */
export function formatLocalTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString(undefined, { hour12: false });
}

export function formatLocalDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, { hour12: false });
}

/** `formatLocalTime` + the exact UTC string alongside it, one ready-to-render display string. */
export function formatLocalWithUtc(value: string | null | undefined): string {
  if (!value) return '—';
  return `${formatLocalTime(value)} (${formatUtcTime(value)})`;
}

/** `formatLocalDateTime` + the exact UTC string alongside it. */
export function formatLocalDateTimeWithUtc(value: string | null | undefined): string {
  if (!value) return '—';
  return `${formatLocalDateTime(value)} (${formatUtc(value)})`;
}

/**
 * Conversion for chart PIXEL positioning only (T-99, personal project).
 * NEVER use for money calculation/comparison — the candlestick chart
 * requires `number`, so this is the one sanctioned escape hatch (AC-25's
 * point is protecting comparisons/calculations from rounding, not screen
 * coordinates).
 */
export function toChartNumber(value: Money): number {
  return Number(value);
}

/** Money subtraction — same integer/BigInt arithmetic as `multiply`. */
export function subtract(a: Money | undefined, b: Money | null | undefined): Money | null {
  if (!a || !b) return null;
  const left = toScaled(a);
  const right = toScaled(b);
  if (left === null || right === null) return null;
  const scale = Math.max(left.scale, right.scale);
  const diff =
    left.value * 10n ** BigInt(scale - left.scale) - right.value * 10n ** BigInt(scale - right.scale);
  return fromScaled(diff, scale, 2);
}

/** Sum of money strings' absolute values — same integer/BigInt arithmetic as `multiply`. */
export function sumMoney(values: (Money | null | undefined)[]): Money {
  const parsed = values
    .map((v) => (v ? toScaled(v.replace('-', '')) : null))
    .filter((v): v is Scaled => v !== null);
  const maxScale = parsed.reduce((max, p) => Math.max(max, p.scale), 0);
  const total = parsed.reduce((sum, p) => sum + p.value * 10n ** BigInt(maxScale - p.scale), 0n);
  return fromScaled(total, maxScale, 2);
}

/**
 * Total exposure as a % of effective equity, plus how close that is to the
 * configured cap (T-99) — one purpose-built reading for the Dashboard's
 * exposure tile, not a generic percent util. `Number()` use is the same
 * sanctioned display-only exception as `toChartNumber`; `ratioOfLimit` is
 * for color/threshold decisions only, never shown as text itself.
 */
export function exposureReading(
  totalExposure: Money | null | undefined,
  effectiveEquity: Money | null | undefined,
  limitPct: string | null | undefined,
): { pct: string; ratioOfLimit: number } | null {
  if (totalExposure == null || effectiveEquity == null || limitPct == null) return null;
  const equity = Math.abs(Number(effectiveEquity));
  const limit = Number(limitPct);
  if (!Number.isFinite(equity) || equity === 0 || !Number.isFinite(limit) || limit === 0) return null;
  const pct = (Number(totalExposure) / equity) * 100;
  if (!Number.isFinite(pct)) return null;
  return { pct: `${pct.toFixed(1)}%`, ratioOfLimit: pct / limit };
}

/**
 * Percent-change badge text ONLY (T-99) — same sanctioned exception as
 * `toChartNumber`: a display label, never fed back into a calculation or
 * comparison. `of` is the cost basis (e.g. `market_value - unrealized_pl`);
 * returns null when it's zero/missing rather than showing a meaningless "0%".
 */
export function formatPercent(value: Money | null | undefined, of: Money | null | undefined): string | null {
  if (value === null || value === undefined || of === null || of === undefined) return null;
  const base = Math.abs(Number(of));
  if (!Number.isFinite(base) || base === 0) return null;
  const pct = (Number(value) / base) * 100;
  if (!Number.isFinite(pct)) return null;
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

/** Seconds → `12:34`. Wind-down countdown. */
export function formatCountdown(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}
