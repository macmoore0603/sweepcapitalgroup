import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { loadRules } from '../ledger.mjs';

// APEX_PINE_PATH overrides the location (used to check this test against a scratch copy).
const PINE = process.env.APEX_PINE_PATH ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'ApexEvalLab.pine');
const BEGIN = '// <<RULES:BEGIN>>';
const END = '// <<RULES:END>>';

/** "HH:MM" (ET) -> minutes after midnight. */
function etClockToMinutes(s) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(s ?? ''));
  assert.ok(m, `rules.json flatByEt must be "HH:MM", got ${JSON.stringify(s)}`);
  return Number(m[1]) * 60 + Number(m[2]);
}

/** Expected Pine constants, each read from rules.json (null = Pine `na`). */
export function expectedPineConstants(rules) {
  const e = rules.evaluation;
  const pa = rules.performanceAccount;
  const t = pa.tiers;
  const out = {
    START_BAL: rules.startBalance,
    EVAL_TARGET: e.profitTarget,
    EVAL_DD: e.maxDrawdown,
    EVAL_STOP_RITHMIC: e.thresholdStopRithmic,
    EVAL_STOP_TRADOVATE: e.thresholdStopTradovate ?? null,
    EVAL_DLL: e.dailyLossLimit ?? null,
    EVAL_MAX_MINIS: e.maxContractsMini,
    EVAL_ACCESS_DAYS: e.accessDays,
    PA_DD: pa.maxDrawdown,
    PA_STOP: pa.thresholdStop,
    MICROS_PER_MINI: rules.microsPerMini,
    FLAT_BY_ET_MIN: etClockToMinutes(rules.flatByEt),
  };
  for (let i = 1; i <= 3; i++) out[`PA_T${i + 1}_PROFIT`] = t[i].minProfit;
  for (let i = 0; i < 4; i++) {
    out[`PA_T${i + 1}_MINIS`] = t[i].maxContractsMini;
    out[`PA_T${i + 1}_DLL`] = t[i].dailyLossLimit;
  }
  return out;
}

/** Parse `float|int NAME = number|na` lines between the RULES markers (na -> null). */
export function parsePineRulesBlock(src) {
  const b = src.indexOf(BEGIN);
  const e = src.indexOf(END);
  assert.ok(b >= 0, `missing "${BEGIN}" marker`);
  assert.ok(e > b, `missing "${END}" marker after "${BEGIN}"`);
  const block = src.slice(b + BEGIN.length, e);
  const values = {};
  for (const line of block.split(/\r?\n/)) {
    const m = /^\s*(?:var\s+)?(?:float|int)\s+([A-Z][A-Z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d+)?|na)\b/.exec(line);
    if (m) values[m[1]] = m[2] === 'na' ? null : Number(m[2]);
  }
  return values;
}

const pineExists = existsSync(PINE);

test(
  'ApexEvalLab.pine RULES block matches rules.json',
  { skip: pineExists ? false : `skipped: ${PINE} not found yet (it is being written in parallel)` },
  () => {
    const rules = loadRules();
    const got = parsePineRulesBlock(readFileSync(PINE, 'utf8'));
    const want = expectedPineConstants(rules);
    const missing = Object.keys(want).filter((k) => !(k in got));
    assert.deepEqual(missing, [], `Pine RULES block is missing: ${missing.join(', ')}`);
    for (const [k, v] of Object.entries(want)) {
      assert.equal(got[k], v, `${k}: Pine has ${got[k]}, rules.json has ${v}`);
    }
  },
);

test('Pine RULES block parser reads float/int constants', () => {
  const src = [
    'strategy("x")',
    BEGIN,
    'float START_BAL = 50000.0',
    'int   EVAL_MAX_MINIS = 6 // comment',
    'var float PA_STOP = 50100',
    'float EVAL_DLL = na',
    'string NOTE = "ignored"',
    END,
    'float OUTSIDE = 1',
  ].join('\n');
  assert.deepEqual(parsePineRulesBlock(src), { START_BAL: 50000, EVAL_MAX_MINIS: 6, PA_STOP: 50100, EVAL_DLL: null });
  assert.throws(() => parsePineRulesBlock('float A = 1'), /missing/);
});
