// PERSONAL-3 · contracts · CONTRACT_PUBLISH · 2026-09-16
// Prism дуурайлтыг асааж, нийтлэгдсэн гэрээний ҮЛ ХӨДЛӨХ дүрмүүдийг
// бодит HTTP хариун дээр шалгана. Унавал гэрээ эсвэл жишээ буруу.
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'

const PORT = process.env.MOCK_PORT ?? 4011
const BASE = `http://127.0.0.1:${PORT}`
const MONEY = /^-?[0-9]+\.[0-9]{2}$/
const UTC = /Z$/

// prism-ийг node-оор шууд асаана — .cmd shim нь платформ хооронд тогтворгүй.
const prism = spawn(
  process.execPath,
  [
    'node_modules/@stoplight/prism-cli/dist/index.js',
    'mock', 'openapi.yaml', '-p', String(PORT), '-h', '127.0.0.1',
  ],
  { cwd: import.meta.dirname, stdio: 'ignore' }
)

const AUTH = { cookie: 'session=mock-operator-session' }
const get = (p) => fetch(BASE + p, { headers: AUTH }).then(async (r) => [r.status, await r.json()])
// requestBody тодорхойлоогүй зам руу бие илгээвэл гэрээ 415 буцаадаг —
// тиймээс бие өгөөгүй үед content-type ч илгээхгүй.
const post = (p, body, headers = {}) =>
  fetch(BASE + p, {
    method: 'POST',
    headers: body === undefined
      ? { ...AUTH, ...headers }
      : { 'content-type': 'application/json', ...AUTH, ...headers },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }).then(async (r) => [r.status, await r.json()])

async function waitUp() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(BASE + '/health')
      if (r.ok) return
    } catch {}
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error('prism mock 60 секундэд босоогүй')
}

const envelope = (body, where) => {
  for (const k of ['source', 'as_of', 'stale', 'system_state'])
    assert.ok(k in body, `${where}: дугтуйн '${k}' талбар дутуу`)
  assert.match(body.as_of, UTC, `${where}: as_of нь UTC (Z) биш`)
  assert.ok(
    ['alpaca_live', 'alpaca_paper', 'backtest'].includes(body.source),
    `${where}: source утга гэрээнээс гадуур`
  )
}

try {
  await waitUp()

  // 1. Уншилтын замууд — дугтуй, мөнгө, UTC
  for (const p of ['/health', '/account', '/positions', '/orders', '/attribution',
                   '/approvals', '/agent-decisions', '/providers', '/tuning/parameters',
                   '/system/state']) {
    const [status, body] = await get(p)
    assert.equal(status, 200, `${p}: 200 хүлээсэн, ${status} ирэв`)
    envelope(body, p)
  }

  const [, acct] = await get('/account')
  for (const k of ['equity', 'cash', 'buying_power'])
    assert.match(acct.account[k], MONEY, `/account: ${k} нь fixed-point decimal биш (AC-25)`)

  // 2. Attribution — «хэн юунд арилжаа хийж байна» (FR-11, AC-30)
  const [, attr] = await get('/attribution')
  const origins = attr.groups.map((g) => g.origin)
  assert.ok(origins.includes('research_agent'), '/attribution: AI-ийн бүлэг байхгүй')
  assert.ok(origins.includes('manual_operator'), '/attribution: гарын бүлэг байхгүй')
  assert.ok(origins.includes('external'), '/attribution: external бүлэг байхгүй')

  // 3. Позиц бүр origin-той (AC-29) — «эзэнгүй» мөр байхгүй
  const [, pos] = await get('/positions')
  for (const p of pos.positions)
    assert.ok(
      ['research_agent', 'auto_tuning', 'manual_operator', 'external'].includes(p.origin),
      `/positions: ${p.symbol} origin-гүй`
    )

  // 4. Төлөвийн машин — wind-down ба kill switch тусдаа төлөв буцаана (AC-34…AC-37)
  const [wdStatus, wd] = await post('/system/wind-down')
  assert.equal(wdStatus, 200)
  assert.equal(wd.state, 'winding_down', 'wind-down нь winding_down буцаах ёстой')
  assert.ok(wd.wind_down_deadline, 'wind-down нь хугацааны хязгаарыг заавал буцаана (AC-36)')

  const [ksStatus, ks] = await post('/kill-switch', { reason: 'test' })
  assert.equal(ksStatus, 200)
  assert.equal(ks.state, 'halted', 'kill switch нь halted буцаах ёстой')

  // 5. Гарын order — Risk-ийн шалгалтын мөрүүдтэй хамт буцна (AC-31…AC-33)
  const [moStatus, mo] = await post(
    '/orders/manual',
    { symbol: 'MSFT', side: 'sell', qty: '12', order_type: 'market', time_in_force: 'day' },
    { 'Idempotency-Key': '7f2b1c33-8d4e-4a5f-9b60-112233445566' }
  )
  assert.equal(moStatus, 202, `/orders/manual: 202 хүлээсэн, ${moStatus} ирэв`)
  assert.equal(mo.order.origin, 'manual_operator', 'гарын order нь manual_operator origin-той байх ёстой')
  assert.ok(mo.risk.checks.length > 0, 'гарын order нь Risk-ийн шалгалтын мөргүй буцав')

  console.log('дуурайлтын шалгалт OK — 10 зам, 5 үл хөдлөх дүрэм')
} finally {
  prism.kill()
}
