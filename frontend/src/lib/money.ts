/**
 * Мөнгөний хилийн дүрэм — frontend тал (AC-25).
 *
 * Fixed-point тэмдэгт мөрийг ХЭЗЭЭ Ч `Number(...)` болгохгүй: 0.1 + 0.2-ийн
 * алдаа нь эквити дээр харагдахгүй ч эрсдэлийн тооцоонд дамжина. Тиймээс
 * форматлалт нь ЗӨВХӨН тэмдэгт мөрөөр ажиллана.
 *
 * ESLint нь энэ файлаас гадуур `Number()`-ийг хориглоно.
 */

const GROUP = /\B(?=(\d{3})+(?!\d))/g;

export type Money = string;
export type Quantity = string;

export function isNegative(value: Money | null | undefined): boolean {
  return typeof value === 'string' && value.trimStart().startsWith('-');
}

/** `-1234.56` → `-1,234.56`. Тэмдэгт мөр орж, тэмдэгт мөр гарна. */
export function formatMoney(value: Money | null | undefined, currency = '$'): string {
  if (value === null || value === undefined || value === '') return '—';
  const negative = isNegative(value);
  const [whole = '0', fraction] = value.replace('-', '').split('.');
  const grouped = whole.replace(GROUP, ',');
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return `${negative ? '−' : ''}${currency}${body}`;
}

/** Ширхэг — валютын тэмдэггүй, бүлэглэлтэй. */
export function formatQuantity(value: Quantity | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const negative = isNegative(value);
  const [whole = '0', fraction] = value.replace('-', '').split('.');
  const grouped = whole.replace(GROUP, ',');
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return `${negative ? '−' : ''}${body}`;
}

/**
 * Тооцоолсон notional = qty × үнэ. Хоёулаа тэмдэгт мөр, үр дүн ч тэмдэгт мөр.
 * Бүхэл тооны арифметик — float огт оролцохгүй.
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
    // Таслах — банкирын тоймлолт биш. Notional нь урьдчилсан тооцоо тул
    // бага тал руу таслах нь operator-ыг хэтрүүлэн итгүүлэхгүй.
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

/** UTC timestamp → `14:30:00Z`. Локал бүс рүү ХЭЗЭЭ Ч хөрвүүлэхгүй (AC-26). */
export function formatUtcTime(value: string | null | undefined): string {
  if (!value) return '—';
  return `${value.slice(11, 19)}Z`;
}

export function formatUtc(value: string | null | undefined): string {
  if (!value) return '—';
  return `${value.slice(0, 10)} ${value.slice(11, 19)}Z`;
}

/** Секунд → `12:34`. Wind-down-ийн тоолуур. */
export function formatCountdown(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}
