/**
 * `src/lib/api.generated.ts` нь `docs/PERSONAL-3/contracts.yaml`-аас
 * ҮҮСГЭГДЭНЭ. Гараар засвал энэ шалгалт унана — гэрээ ба клиентийн төрөл
 * хоорондын чимээгүй зөрүү үүсэхгүй (LLD §16.1).
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const target = 'src/lib/api.generated.ts';
const dir = mkdtempSync(join(tmpdir(), 'p3-api-'));
const fresh = join(dir, 'api.ts');

try {
  execFileSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', '../contracts/openapi.yaml', '-o', fresh],
    { stdio: 'inherit' },
  );
  const generated = readFileSync(fresh, 'utf8');
  const committed = readFileSync(target, 'utf8');
  if (generated !== committed) {
    console.error(
      `${target} нь гэрээтэй зөрүүтэй. \`npm run generate:api\` ажиллуулна уу.`,
    );
    process.exit(1);
  }
  console.log(`${target} — гэрээтэй тэнцүү.`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
