// run-tests.mjs - entry point used when `node --test planner/test/` is given the test directory.
// Node 22 treats a directory argument to --test as a single entry file and resolves it through
// test/package.json "main", which points here; this imports every test/*.test.mjs so node:test runs them
// all. (Running `node --test` with no arguments, or with the test files themselves, also works.)
import { readdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const dir = join(dirname(fileURLToPath(import.meta.url)), 'test');
for (const f of readdirSync(dir).filter((n) => n.endsWith('.test.mjs')).sort()) {
  await import(pathToFileURL(join(dir, f)).href);
}
