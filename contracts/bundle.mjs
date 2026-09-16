// PERSONAL-3 · contracts · CONTRACT_PUBLISH · 2026-09-16
// Нэг эх сурвалж: contracts/*.yaml. Энэ скрипт нь Hefesto-д бүртгэгддэг
// нэгдсэн `docs/PERSONAL-3/contracts.yaml` файлыг ДАХИН УГСАРНА.
//   node bundle.mjs          — угсарч бичнэ
//   node bundle.mjs --check  — зөрүүтэй бол exit 1 (CI / npm test)
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, '..', 'docs', 'PERSONAL-3', 'contracts.yaml')

const PARTS = [
  ['--- #! 1/3 OpenAPI — Backend REST API', 'openapi.yaml'],
  ['--- #! 2/3 AsyncAPI — WebSocket сувгууд', 'asyncapi.yaml'],
  ['--- #! 3/3 Tool Contract v1 — Agent Gateway ↔ ямар ч LLM provider', 'tool-contract.v1.yaml'],
]

const lf = (s) => s.split('\r\n').join('\n')
const read = (f) => lf(readFileSync(join(here, f), 'utf8'))

const bundled =
  read('bundle-preamble.yaml') +
  PARTS.map(([marker, file]) => marker + '\n' + read(file)).join('')

if (process.argv.includes('--check')) {
  if (lf(readFileSync(out, 'utf8')) !== bundled) {
    console.error('contracts.yaml нь contracts/*.yaml-аас хоцорсон. `npm run bundle` ажиллуулаад commit хий.')
    process.exit(1)
  }
  console.log('bundle шалгалт OK')
} else {
  writeFileSync(out, bundled)
  console.log('bundle бичигдэв:', out)
}
