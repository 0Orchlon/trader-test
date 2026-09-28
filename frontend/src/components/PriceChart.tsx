/**
 * Reusable candlestick + trend-line chart for one symbol (extracted from
 * `TradeChart` — same `lightweight-charts` setup, now shared with the
 * Manual order page's symbol snapshot, which has no `Position` to hand it).
 *
 * REAL candles from `GET /market/bars/{symbol}`. `entryPrice` is optional —
 * pass it to draw the dashed entry-price line; omit it for a symbol with
 * no open position (nothing to mark).
 */
import { useEffect, useRef } from 'react';
import { Alert, Loader } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import {
  CandlestickSeries,
  createChart,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';

import { api } from '@/lib/api';
import { toChartNumber } from '@/lib/money';

// Canvas fillStyle can't resolve CSS custom properties, so the theme's
// green.6/red.6 are read from the DOM once at mount — one palette, no
// duplicated hex literals (design spec §4).
function themeColor(varName: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

export function PriceChart({
  symbol,
  entryPrice,
  height = 360,
}: {
  symbol: string;
  entryPrice?: string | null;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const trendRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Recent window, not a full day — a day of 5-min bars is mostly noise
  // for "what's this doing right now". 60 min = 12 candles.
  const bars = useQuery({
    queryKey: ['bars', symbol],
    queryFn: () => api.bars(symbol, '5Min', 60),
    refetchInterval: 60_000,
    enabled: symbol !== '',
  });

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      height,
      layout: { background: { color: 'transparent' }, textColor: '#666' },
      grid: { vertLines: { visible: false }, horzLines: { color: '#eee' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const up = themeColor('--mantine-color-green-6', '#2f9e44');
    const down = themeColor('--mantine-color-red-6', '#e03131');
    const series = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderVisible: false,
      wickUpColor: up,
      wickDownColor: down,
    });
    const trend = chart.addSeries(LineSeries, {
      color: '#868e96',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      lastValueVisible: false,
      priceLineVisible: false,
      title: 'trend',
    });
    chartRef.current = chart;
    seriesRef.current = series;
    trendRef.current = trend;
    // If the chart mounts before a `Modal`/collapsible's fade transition
    // finishes, `clientWidth` can be 0 — `window resize` never catches this
    // (the window itself hasn't changed size). `ResizeObserver` watches the
    // container itself and picks up the real width once the transition ends.
    // A width-0 apply is also what jsdom's minimal layout engine (no real
    // box model) hands us in every test — skip it rather than feed the
    // chart a size it can't draw at.
    const resize = () => {
      const width = containerRef.current?.clientWidth ?? 0;
      if (width > 0) chart.applyOptions({ width });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      trendRef.current = null;
    };
    // Chart is constructed ONCE per mount — data comes in via the effect below.
  }, [height]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !bars.data?.bars) return;
    const rows = bars.data.bars;
    series.setData(
      rows.map((bar) => ({
        time: (Date.parse(bar.t) / 1000) as never,
        open: toChartNumber(bar.open),
        high: toChartNumber(bar.high),
        low: toChartNumber(bar.low),
        close: toChartNumber(bar.close),
      })),
    );

    // Trend line: least-squares fit over visible closes, drawn across the
    // window and a bit past the last candle. This is NOT a prediction — a
    // plain linear extrapolation of recent price, labeled "trend" so it's
    // never mistaken for a forecast on a trading dashboard.
    const trend = trendRef.current;
    const times = rows.map((bar) => Date.parse(bar.t));
    const first = times[0];
    const last = times[times.length - 1];
    if (trend && rows.length >= 2 && first !== undefined && last !== undefined) {
      const n = rows.length;
      const points = rows.map((bar, i) => ({ x: i, y: toChartNumber(bar.close) }));
      const sumX = points.reduce((a, p) => a + p.x, 0);
      const sumY = points.reduce((a, p) => a + p.y, 0);
      const sumXY = points.reduce((a, p) => a + p.x * p.y, 0);
      const sumXX = points.reduce((a, p) => a + p.x * p.x, 0);
      const denom = n * sumXX - sumX * sumX;
      const slope = denom === 0 ? 0 : (n * sumXY - sumX * sumY) / denom;
      const intercept = (sumY - slope * sumX) / n;

      const barMs = n > 1 ? (last - first) / (n - 1) : 0;
      const extra = Math.max(2, Math.round(n * 0.2)); // extend ~20% past the last candle
      trend.setData(
        Array.from({ length: n + extra }, (_, x) => ({
          time: Math.round((last + (x - (n - 1)) * barMs) / 1000) as never,
          value: slope * x + intercept,
        })),
      );
    } else {
      trend?.setData([]);
    }

    if (entryPrice) {
      series.createPriceLine({
        price: toChartNumber(entryPrice),
        color: '#f08c00',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'entry',
      });
    }
    chartRef.current?.timeScale().fitContent();
  }, [bars.data, entryPrice]);

  return (
    <>
      {bars.isLoading ? <Loader size="sm" /> : null}
      {bars.error ? (
        <Alert color="red" icon={<IconAlertTriangle size={16} />}>
          {(bars.error as Error).message}
        </Alert>
      ) : null}
      <div
        ref={containerRef}
        data-testid="price-chart-canvas"
        style={{ width: '100%', height }}
      />
    </>
  );
}
