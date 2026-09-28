/**
 * Generic monospace/tabular-nums wrapper for non-directional numeric-ish
 * values: ids, timestamps, limits, counts (design spec §2.2).
 */
import { Text, type TextProps } from '@mantine/core';

export function Num({ children, ...props }: { children: React.ReactNode } & TextProps) {
  return (
    <Text ff="monospace" style={{ fontVariantNumeric: 'tabular-nums' }} {...props}>
      {children}
    </Text>
  );
}
