import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  loadRules,
  validateRules,
  makeEvalLedger,
  makePaLedger,
  observe,
  stepTrade,
  closeTrade,
  checkExpiry,
  startDay,
  balance,
  contractCap,
  evalStopLevel,
  ACTIVE,
  PASSED,
  BREACHED,
  EXPIRED,
} from '../ledger.mjs';
import { addDays } from '../time.mjs';

const rules = loadRules();
const S = rules.startBalance;
const E = rules.evaluation;
const PA = rules.performanceAccount;

test('rules.json values the spec describes (sanity check of the file the engine loads)', () => {
  assert.equal(S - E.maxDrawdown, 48000);
  assert.equal(E.thresholdStopRithmic, 53000);
  assert.equal(E.thresholdStopTradovate, null);
  assert.equal(PA.thresholdStop, 50100);
  assert.equal(E.profitTarget, 3000);
});

test('rules the planner does not model must stay unset in rules.json', () => {
  for (const [k, v] of [
    ['dailyLossLimit', 500],
    ['consistency', 0.3],
    ['minTradingDays', 7],
  ]) {
    const r = structuredClone(rules);
    r.evaluation[k] = v;
    assert.throws(() => validateRules(r), new RegExp(`evaluation\\.${k} .*not modelled`), k);
  }
  const ok = structuredClone(rules);
  Object.assign(ok.evaluation, { dailyLossLimit: null, consistency: null, minTradingDays: 0 });
  assert.equal(validateRules(ok), ok);
});

test('threshold starts at startBalance - maxDrawdown (48000) and peak at startBalance', () => {
  for (const L of [makeEvalLedger(rules), makeEvalLedger(rules, { feed: 'tradovate' }), makePaLedger(rules)]) {
    assert.equal(L.peak, S);
    assert.equal(L.threshold, S - E.maxDrawdown);
    assert.equal(L.threshold, 48000);
    assert.equal(L.realized, 0);
    assert.equal(L.status, ACTIVE);
  }
});

test('peak includes unrealized (open) profit', () => {
  const L = makeEvalLedger(rules);
  observe(L, balance(L, 700)); // open +700, nothing realized
  assert.equal(L.realized, 0);
  assert.equal(L.peak, S + 700);
  assert.equal(L.threshold, S + 700 - E.maxDrawdown);

  // A trade that runs +900 open and is closed flat still drags the threshold up.
  const M = makeEvalLedger(rules);
  stepTrade(M, { favorable: 900, adverse: -100, close: 0 });
  assert.equal(M.realized, 0);
  assert.equal(M.peak, S + 900);
  assert.equal(M.threshold, S + 900 - E.maxDrawdown);
  assert.equal(M.status, ACTIVE);
});

test('threshold never decreases', () => {
  const L = makeEvalLedger(rules);
  observe(L, S + 1000);
  const t = L.threshold;
  assert.equal(t, S + 1000 - E.maxDrawdown);
  for (const b of [S, S + 500, S - 500, S + 999]) {
    observe(L, b);
    assert.equal(L.threshold, t);
  }
  assert.equal(L.peak, S + 1000);
});

test('breach when balance touches the threshold exactly (<=), not just below it', () => {
  const L = makeEvalLedger(rules);
  assert.equal(observe(L, L.threshold + 0.01), ACTIVE);
  assert.equal(observe(L, L.threshold), BREACHED);

  const M = makeEvalLedger(rules);
  observe(M, S + 500);
  assert.equal(M.threshold, S + 500 - E.maxDrawdown);
  assert.equal(closeTrade(M, 500 - E.maxDrawdown), BREACHED); // flat exactly on the trailed threshold

  // Breached is terminal: later trades do nothing.
  const before = M.realized;
  stepTrade(M, { favorable: 5000, adverse: 0, close: 5000 });
  assert.equal(M.realized, before);
  assert.equal(M.status, BREACHED);
});

test('Rithmic/WealthCharts eval stops trailing at 53000; Tradovate keeps trailing', () => {
  assert.equal(evalStopLevel(rules, 'Rithmic/WealthCharts'), E.thresholdStopRithmic);
  assert.equal(evalStopLevel(rules, 'tradovate'), Infinity);
  const R = makeEvalLedger(rules, { feed: 'rithmic' });
  const T = makeEvalLedger(rules, { feed: 'tradovate' });
  for (const b of [S + 4000, S + 5000, S + 6000]) {
    observe(R, b);
    observe(T, b);
  }
  assert.equal(R.threshold, E.thresholdStopRithmic);
  assert.equal(R.threshold, 53000);
  assert.equal(T.threshold, S + 6000 - E.maxDrawdown); // 54000, still trailing
  assert.ok(T.threshold > R.threshold);
  assert.equal(R.status, ACTIVE);
  assert.equal(T.status, ACTIVE);
});

test('PA threshold stops at 50100 once the peak reaches 52100', () => {
  const P = makePaLedger(rules);
  observe(P, PA.thresholdStop + PA.maxDrawdown - 100); // peak 52000
  assert.equal(P.threshold, S); // 50000
  observe(P, PA.thresholdStop + PA.maxDrawdown); // peak 52100
  assert.equal(P.threshold, PA.thresholdStop);
  assert.equal(P.threshold, 50100);
  observe(P, S + 8000);
  assert.equal(P.threshold, PA.thresholdStop);
  assert.equal(observe(P, PA.thresholdStop), BREACHED);
});

test('conservative and adverse-first orderings differ on a crafted trade', () => {
  const trade = { favorable: 1500, adverse: -1000, close: 500 };
  const C = makeEvalLedger(rules, { order: 'conservative' });
  const A = makeEvalLedger(rules, { order: 'adverse-first' });
  // conservative: +1500 lifts the threshold to 49500 first, then the -1000 dip (49000) breaches.
  assert.equal(stepTrade(C, trade), BREACHED);
  assert.equal(C.threshold, S + 1500 - E.maxDrawdown);
  // adverse-first: the -1000 dip meets the original 48000 threshold, then +1500, then close +500.
  assert.equal(stepTrade(A, trade), ACTIVE);
  assert.equal(A.realized, 500);
  assert.equal(A.peak, S + 1500);
  assert.equal(A.threshold, S + 1500 - E.maxDrawdown);
});

test('pass needs flat realized >= target; open profit alone never passes', () => {
  const L = makeEvalLedger(rules);
  observe(L, balance(L, E.profitTarget + 500)); // open +3500
  assert.equal(L.status, ACTIVE);
  assert.equal(closeTrade(L, E.profitTarget - 1), ACTIVE); // flat at +2999
  assert.equal(closeTrade(L, 1), PASSED); // flat at exactly +3000
  assert.equal(L.realized, E.profitTarget);

  // A trade that runs +4000 open but closes +2999 does not pass (adverse-first: it never dipped after the
  // run-up). Under the default conservative order the same trade's 0 low is assumed to come after the
  // +4000 high, which touches the lifted 52000 threshold.
  const M = makeEvalLedger(rules, { order: 'adverse-first' });
  assert.equal(stepTrade(M, { favorable: 4000, adverse: 0, close: 2999 }), ACTIVE);
  assert.equal(M.threshold, S + 4000 - E.maxDrawdown);
  assert.equal(stepTrade(M, { favorable: 1, adverse: 0, close: 1 }), PASSED);
  assert.equal(stepTrade(makeEvalLedger(rules), { favorable: 4000, adverse: 0, close: 2999 }), BREACHED);

  // Cent amounts that add up to exactly +3,000.00 pass (no binary floating-point shortfall).
  const closes = [218.89, 387.23, 534.02, 343.83, 462.54, 24.31, 551.43, 477.75];
  assert.ok(closes.reduce((a, b) => a + b, 0) < E.profitTarget, 'raw float sum falls short of 3000');
  const F = makeEvalLedger(rules);
  for (const x of closes) closeTrade(F, x);
  assert.equal(F.realized, E.profitTarget);
  assert.equal(F.status, PASSED);

  // PA ledgers have no profit target.
  const P = makePaLedger(rules);
  closeTrade(P, E.profitTarget + 1000);
  assert.equal(P.status, ACTIVE);
});

test('evaluation expires after the access window (calendar days from the first day)', () => {
  const first = '2026-01-05';
  const L = makeEvalLedger(rules);
  assert.equal(startDay(L, first), ACTIVE);
  assert.equal(L.firstDay, first);
  assert.equal(startDay(L, addDays(first, E.accessDays - 1)), ACTIVE); // 2026-02-03: last day inside
  assert.equal(addDays(first, E.accessDays), '2026-02-04');
  assert.equal(checkExpiry(L, addDays(first, E.accessDays)), EXPIRED);

  // A passed attempt does not later expire.
  const M = makeEvalLedger(rules, { firstDay: first });
  closeTrade(M, E.profitTarget);
  assert.equal(checkExpiry(M, addDays(first, 90)), PASSED);
});

test('eval contract cap: minis and micros', () => {
  const L = makeEvalLedger(rules);
  assert.equal(contractCap(L, 'mini'), E.maxContractsMini);
  assert.equal(contractCap(L, 'micro'), E.maxContractsMini * rules.microsPerMini);
});
