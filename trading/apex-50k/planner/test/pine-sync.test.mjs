import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { loadRules } from '../ledger.mjs';
import { loadTradeifyRules } from '../tradeify.mjs';

// APEX_PINE_PATH / TRADEIFY_PINE_PATH override the locations (used to check this test against a scratch copy).
const PINE = process.env.APEX_PINE_PATH ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'ApexEvalLab.pine');
const TRADEIFY_PINE =
  process.env.TRADEIFY_PINE_PATH ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'tradeify-50k', 'TradeifySignals.pine');
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

/** Expected TradeifySignals.pine RULES constants, each read from tradeify-50k/rules.json. */
export function expectedTradeifyPineConstants(rules) {
  const s = rules.session;
  const g = rules.plans.growth;
  const gp = g.payout;
  const flex = rules.plans['select-flex'].scaling;
  // The Pine holds one cap per payout 1-3 and one repeated cap after; one consistency figure.
  assert.equal(gp.caps.length, 4, 'plans.growth.payout.caps: the Pine holds GROWTH_CAP_1..3 and GROWTH_CAP_LAST');
  assert.equal(gp.capsRepeatLast, true, 'plans.growth.payout.capsRepeatLast: the Pine repeats GROWTH_CAP_LAST');
  assert.equal(g.consistency.length, 1, 'plans.growth.consistency: the Pine holds one GROWTH_CONSISTENCY');
  return {
    START_BAL: rules.startBalance,
    TMD: rules.drawdown.amount,
    TMD_LOCKED_FLOOR: rules.drawdown.lockedFloor,
    DLL_BASE: g.dailyLossLimit,
    DLL_RAISE_AT: g.dllRaise.atBalance,
    DLL_RAISED: g.dllRaise.to,
    DLL_SELECT_DAILY: rules.plans['select-daily'].dailyLossLimit,
    MAX_MINIS: g.maxContractsMini,
    MAX_MINIS_LEGACY: g.legacy.maxContractsMini,
    SEL_T2_PROFIT: flex[1].minProfit,
    SEL_T3_PROFIT: flex[2].minProfit,
    SEL_T1_MINIS: flex[0].maxContractsMini,
    SEL_T2_MINIS: flex[1].maxContractsMini,
    SEL_T3_MINIS: flex[2].maxContractsMini,
    MICROS_PER_MINI: rules.microsPerMini,
    FLAT_BY_CAP_MIN: etClockToMinutes(s.flatByEt),
    EARLY_FLAT_BY_MIN: etClockToMinutes(s.earlyCloseFlatByEt),
    SESSION_START_H: Math.floor(etClockToMinutes(s.startEt) / 60),
    SESSION_END_H: Math.floor(etClockToMinutes(s.endEt) / 60),
    GROWTH_QUAL_DAYS: gp.minQualifyingDays,
    GROWTH_QUAL_DAY_ABOVE: gp.qualifyingDayProfitAbove,
    GROWTH_MIN_BAL: gp.minBalance,
    GROWTH_MIN_BAL_LEGACY: g.legacy.minBalance,
    GROWTH_MIN_PAYOUT: gp.minPayout,
    GROWTH_CAP_1: gp.caps[0],
    GROWTH_CAP_2: gp.caps[1],
    GROWTH_CAP_3: gp.caps[2],
    GROWTH_CAP_LAST: gp.caps[3],
    GROWTH_CONSISTENCY: g.consistency[0],
    PAYOUT_SPLIT: rules.split,
  };
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

test('TradeifySignals.pine RULES block matches tradeify-50k/rules.json', () => {
  const rules = loadTradeifyRules();
  const got = parsePineRulesBlock(readFileSync(TRADEIFY_PINE, 'utf8'));
  const want = expectedTradeifyPineConstants(rules);
  // Every constant in the block must be tied to rules.json, and every expected one must be there.
  assert.deepEqual(Object.keys(got).sort(), Object.keys(want).sort(), 'TradeifySignals.pine RULES block constants differ from the expected set');
  for (const [k, v] of Object.entries(want)) {
    assert.equal(got[k], v, `${k}: TradeifySignals.pine has ${got[k]}, rules.json has ${v}`);
  }
  // One Pine constant serves several plans, so those plans must agree in rules.json.
  const p = rules.plans;
  assert.equal(p.lightning.dailyLossLimit, p.growth.dailyLossLimit, 'DLL_BASE serves Growth and Lightning');
  assert.deepEqual(p.lightning.dllRaise, p.growth.dllRaise, 'DLL_RAISE_AT / DLL_RAISED serve Growth and Lightning');
  assert.equal(p.lightning.maxContractsMini, p.growth.maxContractsMini, 'MAX_MINIS serves Growth and Lightning');
  assert.equal(p.lightning.legacy.maxContractsMini, p.growth.legacy.maxContractsMini, 'MAX_MINIS_LEGACY serves Growth and Lightning');
  assert.deepEqual(p['select-daily'].scaling, p['select-flex'].scaling, 'SEL_* serve Select Flex and Select Daily');
});

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
