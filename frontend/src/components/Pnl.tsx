/**
 * Money/quantity display with color-coded sign (design spec §2.1).
 *
 * Wraps `formatMoney`/`formatQuantity` + `isNegative` from `money.ts` — never
 * reimplements the math, only formatting/color/font.
 */
import { Text, type TextProps } from '@mantine/core';
import { formatMoney, formatPercent, formatQuantity, isNegative, type Money } from '@/lib/money';

export function Pnl({
  value,
  kind = 'money',
  costBasis,
  ...textProps
}: {
  value: Money | null | undefined;
  kind?: 'money' | 'quantity';
  /** Cost basis to show `value` as a percent of, e.g. `market_value - unrealized_pl`. */
  costBasis?: Money | null;
} & TextProps &
  React.HTMLAttributes<HTMLElement>) {
  const negative = isNegative(value);
  const text = kind === 'money' ? formatMoney(value) : formatQuantity(value);
  const color = value == null ? 'dimmed' : negative ? 'red.6' : 'green.7';
  const percent = kind === 'money' ? formatPercent(value, costBasis) : null;
  return (
    <Text
      ff="monospace"
      style={{ fontVariantNumeric: 'tabular-nums' }}
      c={color}
      {...textProps}
    >
      {text}
      {percent ? (
        <Text span size="xs" c={color} ml={4}>
          ({percent})
        </Text>
      ) : null}
    </Text>
  );
}
