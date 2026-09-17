/**
 * T-29 (656) · T-51 (676) — горимын заалт ба гурван товч (AC-20, AC-38).
 *
 * Голууд:
 * - Горим бүр өөр шошго; тодорхойгүй байх нь `paper` гэсэн үг БИШ.
 * - `Зогсоо` нь асуулт БАЙХГҮЙГЭЭР ажиллана.
 * - `Унтраах бэлтгэл` ба `Идэвхжүүл` нь ӨӨР асуулттай.
 * - `Идэвхжүүл`-ийн текст нь backend-ийн `confirmation.prompt`-оос.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ModeBanner } from './ModeBanner';
import { StateBar } from './StateBar';
import { StalenessBanner } from './AppShell';
import { renderWithProviders } from '@/test/render';
import {
  haltedState,
  liveState,
  systemState,
  unmeasuredBreakerState,
  windingDownState,
} from '@/test/fixtures';

describe('ModeBanner (AC-20)', () => {
  it('paper горимыг ил тэмдэглэнэ', () => {
    renderWithProviders(<ModeBanner source="alpaca_paper" />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'alpaca_paper');
    expect(screen.getByText(/PAPER — хуурамч мөнгө/)).toBeInTheDocument();
  });

  it('live горимыг ӨӨР текст, өөр өнгөөр', () => {
    renderWithProviders(<ModeBanner source="alpaca_live" />);
    expect(screen.getByText(/LIVE — БОДИТ МӨНГӨ/)).toBeInTheDocument();
  });

  it('backtest горимыг тусад нь', () => {
    renderWithProviders(<ModeBanner source="backtest" />);
    expect(screen.getByText(/BACKTEST — түүхэн өгөгдөл/)).toBeInTheDocument();
  });

  it('мэдэгдэхгүй горимыг paper гэж ТААМАГЛАХГҮЙ', () => {
    renderWithProviders(<ModeBanner source={undefined} />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'unknown');
    expect(screen.getByText(/ГОРИМ ТОДОРХОЙГҮЙ/)).toBeInTheDocument();
  });

  it('live горим нь source-оос ирнэ, таамаглалаас биш', () => {
    renderWithProviders(<ModeBanner source={liveState.source} />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'alpaca_live');
  });
});

describe('StateBar (AC-38)', () => {
  it('идэвхтэй үед Идэвхжүүл товч идэвхгүй', () => {
    renderWithProviders(<StateBar state={systemState} />);
    expect(screen.getByTestId('state-badge')).toHaveTextContent('ИДЭВХТЭЙ');
    expect(screen.getByTestId('activate')).toBeDisabled();
    expect(screen.getByTestId('wind-down')).toBeEnabled();
    expect(screen.getByTestId('kill-switch')).toBeEnabled();
  });

  it('зогссон үед шалтгаан ил, wind-down идэвхгүй', () => {
    renderWithProviders(<StateBar state={haltedState} />);
    expect(screen.getByTestId('halt-reason')).toHaveTextContent('Өдрийн алдагдлын хязгаар давсан');
    expect(screen.getByTestId('wind-down')).toBeDisabled();
    expect(screen.getByTestId('activate')).toBeEnabled();
  });

  it('wind-down үед үлдсэн хугацааны тоолуур', () => {
    renderWithProviders(<StateBar state={windingDownState} />);
    expect(screen.getByTestId('wind-down-countdown')).toHaveTextContent('12:34');
  });

  it('Зогсоо нь асуулт БАЙХГҮЙГЭЭР шууд ажиллана', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(haltedState), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={systemState} />);
    await userEvent.click(screen.getByTestId('kill-switch'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId('confirm-prompt')).not.toBeInTheDocument();
    expect(String(fetchMock.mock.calls.at(0)?.[0] ?? '')).toContain('/kill-switch');
    vi.unstubAllGlobals();
  });

  it('Унтраах бэлтгэл нь асуулт БАЙХГҮЙГЭЭР шууд ажиллана (N-6)', async () => {
    // Эрсдэл БУУРУУЛАХ үйлдэлд баталгаажуулалт БАЙХГҮЙ — §8.4-ийн гурван
    // үйлдэлд wind-down ороогүй. Ингэснээр UI-д бодлогын текст үлдэхгүй.
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(systemState), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={systemState} />);
    await userEvent.click(screen.getByTestId('wind-down'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls.at(0)?.[0] ?? '')).toContain('/system/wind-down');
    expect(screen.queryByTestId('confirm-prompt')).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('Идэвхжүүлэхийн асуулт нь backend-ийн prompt-оос ирнэ', async () => {
    const problem = {
      type: 'https://personal-3.invalid/problems/confirmation_required',
      title: 'Баталгаажуулалт шаардлагатай',
      status: 409,
      code: 'confirmation_required',
      detail: 'ил баталгаажуулалт шаардлагатай',
      confirmation: {
        token: 'tok-1',
        prompt: 'Системийг ИДЭВХЖҮҮЛЭХ үү? Agent болон алгоритм арилжаагаа дахин эхлүүлнэ.',
        expires_at: '2026-09-16T14:35:00Z',
      },
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(problem), { status: 409 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={haltedState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() =>
      expect(screen.getByTestId('confirm-prompt')).toHaveTextContent(/ИДЭВХЖҮҮЛЭХ үү/),
    );
    // Текст нь UI-д хатуу кодлогдоогүй — ХОЁР эх үүсэхгүй (LLD §16.3).
    expect(screen.getByTestId('confirm-prompt')).not.toHaveTextContent(/унтраах/i);
    vi.unstubAllGlobals();
  });

  it('идэвхжүүлэхийн өмнө breaker-ийн ОДООГИЙН метрик харагдана (AC-37)', async () => {
    const problem = {
      status: 409,
      code: 'confirmation_required',
      title: 'x',
      type: 'x',
      confirmation: { token: 't', prompt: 'Идэвхжүүлэх үү?', expires_at: 'x' },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(problem), { status: 409 })),
    );

    renderWithProviders(<StateBar state={haltedState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() => expect(screen.getByTestId('breaker-metrics')).toBeInTheDocument());
    expect(screen.getByTestId('breaker-metrics')).toHaveTextContent('daily_loss');
    vi.unstubAllGlobals();
  });

  it('хэмжигдээгүй метрик нь «хэвийн» гэж харагдахгүй (B-1)', async () => {
    const problem = {
      status: 409,
      code: 'confirmation_required',
      title: 'x',
      type: 'x',
      confirmation: { token: 't', prompt: 'Идэвхжүүлэх үү?', expires_at: 'x' },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(problem), { status: 409 })),
    );

    renderWithProviders(<StateBar state={unmeasuredBreakerState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() => expect(screen.getByTestId('breaker-metrics')).toBeInTheDocument());
    const row = screen.getByTestId('breaker-metric-api_error_rate');
    expect(row).toHaveTextContent('ХЭМЖИГДЭЭГҮЙ');
    expect(row).not.toHaveTextContent('0.0000');
    vi.unstubAllGlobals();
  });
});

describe('StalenessBanner (AC-2)', () => {
  it('сүүлийн мессежийн UTC хугацааг харуулна', () => {
    renderWithProviders(<StalenessBanner lastSeen="2026-09-16T14:29:58Z" />);
    expect(screen.getByTestId('staleness-banner')).toHaveTextContent('14:29:58Z');
    expect(screen.getByTestId('staleness-banner')).toHaveTextContent(/ХУУЧИН байж болно/);
  });
});
