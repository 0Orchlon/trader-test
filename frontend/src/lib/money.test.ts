/** Money boundary rule (AC-25). Floats NEVER involved. */
import { describe, expect, it } from 'vitest';

import {
  exposureReading,
  formatCountdown,
  formatLocalDateTime,
  formatLocalDateTimeWithUtc,
  formatLocalTime,
  formatLocalWithUtc,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatUtc,
  formatUtcTime,
  isNegative,
  multiply,
  subtract,
  sumMoney,
} from './money';

describe('formatMoney', () => {
  it('groups digits, keeps the decimal point', () => {
    expect(formatMoney('104238.17')).toBe('$104,238.17');
  });

  it('marks negative values visibly', () => {
    expect(formatMoney('-42.00')).toBe('−$42.00');
  });

  it('does not guess when a value is missing', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(undefined)).toBe('—');
  });

  it('does NOT lose digit precision', () => {
    // 9007199254740993 rounds under float. As a string, it doesn't.
    expect(formatMoney('9007199254740993.01')).toBe('$9,007,199,254,740,993.01');
  });
});

describe('multiply', () => {
  it('qty x price — no float error', () => {
    expect(multiply('3', '0.10')).toBe('0.30');
    expect(multiply('10', '221.50')).toBe('2215.00');
  });

  it('does not produce the classic 0.1 + 0.2 rounding error', () => {
    expect(multiply('0.1', '0.2')).toBe('0.02');
  });

  it('multiplies fractional quantities correctly', () => {
    expect(multiply('0.001', '50000.00')).toBe('50.00');
  });

  it('returns null for non-numeric input', () => {
    expect(multiply('abc', '1.00')).toBeNull();
  });
});

describe('formatQuantity', () => {
  it('has no currency symbol', () => {
    expect(formatQuantity('1234.5')).toBe('1,234.5');
  });
});

describe('isNegative', () => {
  it('reads the leading character of the string', () => {
    expect(isNegative('-1.00')).toBe(true);
    expect(isNegative('1.00')).toBe(false);
    expect(isNegative(null)).toBe(false);
  });
});

describe('time formatting', () => {
  it('does NOT convert UTC to local timezone (AC-26)', () => {
    expect(formatUtcTime('2026-09-16T14:30:00Z')).toBe('14:30:00Z');
    expect(formatUtc('2026-09-16T14:30:00Z')).toBe('2026-09-16 14:30:00Z');
  });

  it('does not guess a missing time', () => {
    expect(formatUtcTime(null)).toBe('—');
  });
});

describe('subtract', () => {
  it('subtracts, no float error', () => {
    expect(subtract('229.38', '-4.98')).toBe('234.36');
    expect(subtract('0.3', '0.1')).toBe('0.20');
  });

  it('returns null when either side is missing', () => {
    expect(subtract(undefined, '1.00')).toBeNull();
    expect(subtract('1.00', null)).toBeNull();
  });
});

describe('sumMoney', () => {
  it('sums absolute values across mixed signs and scales', () => {
    expect(sumMoney(['229.38', '-231.59', '38435.00'])).toBe('38895.97');
  });

  it('skips missing entries rather than throwing', () => {
    expect(sumMoney(['10.00', null, undefined, '5.00'])).toBe('15.00');
  });

  it('is "0.00" for an empty list', () => {
    expect(sumMoney([])).toBe('0.00');
  });
});

describe('formatPercent', () => {
  it('signs gains and losses, 2 decimal places', () => {
    expect(formatPercent('16.03', '38408.97')).toBe('+0.04%');
    expect(formatPercent('-4.98', '234.36')).toBe('-2.12%');
  });

  it('returns null when the base is zero or missing', () => {
    expect(formatPercent('1.00', '0')).toBeNull();
    expect(formatPercent('1.00', null)).toBeNull();
    expect(formatPercent(null, '100')).toBeNull();
  });
});

describe('exposureReading', () => {
  it('reads exposure as a % of equity and a ratio of the cap', () => {
    const reading = exposureReading('40000.00', '67489.34', '60');
    expect(reading?.pct).toBe('59.3%');
    expect(reading?.ratioOfLimit).toBeCloseTo(0.988, 3);
  });

  it('returns null when equity or the limit is zero/missing', () => {
    expect(exposureReading('100', '0', '60')).toBeNull();
    expect(exposureReading('100', '1000', null)).toBeNull();
    expect(exposureReading(null, '1000', '60')).toBeNull();
  });
});

describe('local-time display (does NOT touch the AC-26 UTC functions above)', () => {
  it('does not force a UTC "Z" suffix', () => {
    expect(formatLocalTime('2026-09-16T14:30:00Z').endsWith('Z')).toBe(false);
    expect(formatLocalDateTime('2026-09-16T14:30:00Z').endsWith('Z')).toBe(false);
  });

  it('is explicit about a missing timestamp', () => {
    expect(formatLocalTime(null)).toBe('—');
    expect(formatLocalDateTime(undefined)).toBe('—');
  });

  it('keeps the exact UTC value alongside the local one, for audit precision', () => {
    expect(formatLocalWithUtc('2026-09-16T14:30:00Z')).toContain('14:30:00Z');
    expect(formatLocalDateTimeWithUtc('2026-09-16T14:30:00Z')).toContain('2026-09-16 14:30:00Z');
  });

  it('is explicit about a missing timestamp (combined form)', () => {
    expect(formatLocalWithUtc(null)).toBe('—');
    expect(formatLocalDateTimeWithUtc(undefined)).toBe('—');
  });
});

describe('formatCountdown', () => {
  it('turns seconds into mm:ss', () => {
    expect(formatCountdown(754)).toBe('12:34');
    expect(formatCountdown(0)).toBe('00:00');
  });

  it('shows a negative remainder as 00:00', () => {
    expect(formatCountdown(-5)).toBe('00:00');
  });

  it('is explicit about the unknown case', () => {
    expect(formatCountdown(null)).toBe('—');
  });
});
