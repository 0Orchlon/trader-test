/** Мөнгөний хилийн дүрэм (AC-25). Float ХЭЗЭЭ Ч оролцохгүй. */
import { describe, expect, it } from 'vitest';

import {
  formatCountdown,
  formatMoney,
  formatQuantity,
  formatUtc,
  formatUtcTime,
  isNegative,
  multiply,
} from './money';

describe('formatMoney', () => {
  it('бүлэглэнэ, таслалыг хадгална', () => {
    expect(formatMoney('104238.17')).toBe('$104,238.17');
  });

  it('сөрөг утгыг ил тэмдэглэнэ', () => {
    expect(formatMoney('-42.00')).toBe('−$42.00');
  });

  it('байхгүйг таамаглахгүй', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatMoney(undefined)).toBe('—');
  });

  it('оронгийн нарийвчлалыг АЛДАХГҮЙ', () => {
    // 9007199254740993 нь float-д дугуйрна. Тэмдэгт мөрөөр бол алдагдахгүй.
    expect(formatMoney('9007199254740993.01')).toBe('$9,007,199,254,740,993.01');
  });
});

describe('multiply', () => {
  it('qty × үнэ — float-ийн алдаагүй', () => {
    expect(multiply('3', '0.10')).toBe('0.30');
    expect(multiply('10', '221.50')).toBe('2215.00');
  });

  it('0.1 + 0.2-ийн ангиллын алдаа гарахгүй', () => {
    expect(multiply('0.1', '0.2')).toBe('0.02');
  });

  it('бутархай ширхгийг зөв үржүүлнэ', () => {
    expect(multiply('0.001', '50000.00')).toBe('50.00');
  });

  it('тоо биш оролтод null', () => {
    expect(multiply('abc', '1.00')).toBeNull();
  });
});

describe('formatQuantity', () => {
  it('валютын тэмдэггүй', () => {
    expect(formatQuantity('1234.5')).toBe('1,234.5');
  });
});

describe('isNegative', () => {
  it('тэмдэгт мөрийн эхний тэмдэгтээр', () => {
    expect(isNegative('-1.00')).toBe(true);
    expect(isNegative('1.00')).toBe(false);
    expect(isNegative(null)).toBe(false);
  });
});

describe('цагийн формат', () => {
  it('UTC-г локал бүс рүү ХӨРВҮҮЛЭХГҮЙ (AC-26)', () => {
    expect(formatUtcTime('2026-09-16T14:30:00Z')).toBe('14:30:00Z');
    expect(formatUtc('2026-09-16T14:30:00Z')).toBe('2026-09-16 14:30:00Z');
  });

  it('байхгүй цагийг таамаглахгүй', () => {
    expect(formatUtcTime(null)).toBe('—');
  });
});

describe('formatCountdown', () => {
  it('секундийг mm:ss болгоно', () => {
    expect(formatCountdown(754)).toBe('12:34');
    expect(formatCountdown(0)).toBe('00:00');
  });

  it('сөрөг үлдэгдлийг 00:00 гэж харуулна', () => {
    expect(formatCountdown(-5)).toBe('00:00');
  });

  it('мэдэгдэхгүйг ил хэлнэ', () => {
    expect(formatCountdown(null)).toBe('—');
  });
});
