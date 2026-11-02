import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadRules, makePaLedger, stepTrade, startDay, endDay, ACTIVE } from '../ledger.mjs';
import {
  mulberry32,
  makeParametricSource,
  makeEmpiricalSource,
  zeroEdgeWinRate,
  zeroEdgeParams,
  simulateEval,
  simulatePa,
  runSize,
  sweep,
  replayEval,
  groupTradesByDay,
  evalSessionBudgets,
} from '../sim.mjs';
import { addDays, weekday } from '../time.mjs';

const rules = loadRules();
const E = rules.evaluation;
const PO = rules.performanceAccount.payout;

// Symmetric +-$500, zero cost, no excursion beyond the close.
const coinFlip = (winRate = 0.5) =>
  makeParametricSource({
    winRate,
    avgWinR: 1,
    avgLossR: 1,
    riskPerContract: 500,
    mfeOnLosersR: 0,
    maeOnWinnersR: 0,
    tradesPerDay: 2,
    costPerContract: 0,
  });

test('mulberry32 is deterministic and in [0, 1)', () => {
  const a = mulberry32(42);
  const b = mulberry32(42);
  for (let i = 0; i < 1000; i++) {
    const x = a();
    assert.equal(x, b());
    assert.ok(x >= 0 && x < 1);
  }
});

test("trailing disabled: P(pass) matches gambler's ruin maxDrawdown / (maxDrawdown + target)", () => {
  const expected = E.maxDrawdown / (E.maxDrawdown + E.profitTarget);
  assert.equal(expected, 0.4);
  const r = simulateEval(rules, coinFlip(), { contracts: 1, attempts: 20000, tradingDays: 400, trailing: false, seed: 7 });
  assert.ok(Math.abs(r.pPass - expected) < 0.02, `P(pass) ${r.pPass} vs ${expected}`);
  assert.ok(r.pExpire < 0.001, `expiry should be negligible, got ${r.pExpire}`);
  assert.equal(r.passed + r.breached + r.expired, r.attempts);
});

test('trailing drawdown on: P(pass) matches the exact trailing ruin value (4/5)^6', () => {
  const opts = { contracts: 1, attempts: 20000, tradingDays: 400, seed: 7 };
  const fixed = simulateEval(rules, coinFlip(), { ...opts, trailing: false });
  const trailing = simulateEval(rules, coinFlip(), opts);
  assert.ok(trailing.pPass < fixed.pPass - 0.03, `trailing ${trailing.pPass} vs fixed ${fixed.pPass}`);
  // +-$500 steps; the threshold trails 4 steps under the running peak and the target is 6 steps up. From
  // each new peak the next step up comes before a 4-step fall with probability 4/5, six times in a row.
  const down = E.maxDrawdown / 500;
  const up = E.profitTarget / 500;
  assert.deepEqual([down, up], [4, 6]);
  const exact = (down / (down + 1)) ** up; // 0.262144
  assert.ok(Math.abs(trailing.pPass - exact) < 4 * trailing.pPassStdErr, `P(pass) ${trailing.pPass} vs exact ${exact}`);
});

test('parametric winners dip first and exit at the target: a sure winner passes at every size', () => {
  // Winners first dip maeOnWinnersR (up to their stop), then exit at the target. The run to the target is
  // the exit itself, so no winner can fall back from its own high, under either intratrade order.
  for (const maeOnWinnersR of [0, 0.5, 1, 3]) {
    const src = makeParametricSource({ winRate: 1, avgWinR: 2, riskPerContract: 150, maeOnWinnersR, tradesPerDay: 1 });
    for (const order of ['conservative', 'adverse-first']) {
      const s = sweep(rules, src, { attempts: 200, mode: 'eval', order, seed: 2 });
      for (const r of s.results) assert.equal(r.eval.pPass, 1, `mae ${maeOnWinnersR}R, ${order}, ${r.contracts} minis: ${r.eval.pPass}`);
    }
  }
});

test('position values scale with contracts: excursions breach only when multiplied by q', () => {
  // Adverse: a winner that dips 1.4R ($700 per contract; stop at 2R) breaches 48000 at 3 contracts only.
  const dip = makeParametricSource({ winRate: 1, avgWinR: 1, avgLossR: 2, riskPerContract: 500, maeOnWinnersR: 1.4, tradesPerDay: 1 });
  assert.equal(simulateEval(rules, dip, { contracts: 2, attempts: 50 }).pPass, 1);
  const d3 = simulateEval(rules, dip, { contracts: 3, attempts: 50 });
  assert.equal(d3.pBreach, 1);
  assert.equal(d3.tradesSimulated, d3.attempts, 'breaches on the first trade');
  // Favorable: a loser that first runs +$300 per contract lifts the threshold by 3 x 300 at 3 contracts, so
  // its -$1,500 stop breaches on the first trade; at 1 contract it takes 4 losers.
  const runUp = makeParametricSource({ winRate: 0, avgWinR: 1, riskPerContract: 500, mfeOnLosersR: 0.6, tradesPerDay: 1 });
  const r3 = simulateEval(rules, runUp, { contracts: 3, attempts: 50 });
  assert.equal(r3.pBreach, 1);
  assert.equal(r3.tradesSimulated, r3.attempts);
  const r1 = simulateEval(rules, runUp, { contracts: 1, attempts: 50 });
  assert.equal(r1.pBreach, 1);
  assert.equal(r1.tradesSimulated, 4 * r1.attempts);
});

test('round-trip cost is charged once per contract: days to pass is exact', () => {
  // +$500 per contract less $100 cost: 2 contracts net $800 a day -> 4 days; 1 contract $400 -> 8 days.
  const src = makeParametricSource({ winRate: 1, avgWinR: 1, riskPerContract: 500, maeOnWinnersR: 0, tradesPerDay: 1, costPerContract: 100 });
  for (const [q, days] of [
    [2, Math.ceil(E.profitTarget / (2 * 400))],
    [1, Math.ceil(E.profitTarget / 400)],
  ]) {
    const r = simulateEval(rules, src, { contracts: q, attempts: 50 });
    assert.equal(r.pPass, 1);
    assert.deepEqual([r.medianDaysToPass, r.p90DaysToPass], [days, days], `${q} contracts`);
  }
});

test('PA simulation applies size caps, scaling and costs exactly as a hand-run ledger', () => {
  // Sure winner +$500/contract, $100 cost, dips $350/contract: at the tier's size the dip can trip the DLL.
  const p = { winRate: 1, avgWinR: 1, riskPerContract: 500, maeOnWinnersR: 0.7, tradesPerDay: 1, costPerContract: 100 };
  const opts = { contracts: 4, paRuns: 3, horizonDays: 60 };
  const r = simulatePa(rules, makeParametricSource(p), opts);
  const L = makePaLedger(rules);
  let dllDays = 0;
  for (let d = 1; d <= opts.horizonDays; d++) {
    startDay(L, d);
    const q = Math.min(opts.contracts, L.tier.maxContractsMini);
    stepTrade(L, { favorable: 0, adverse: -q * 350, close: q * (500 - 100), cost: q * 100 });
    if (L.status !== ACTIVE) break;
    if (L.dayHalted) dllDays++;
    endDay(L);
    if (L.payouts >= rules.performanceAccount.payout.maxPayouts) break;
  }
  assert.ok(dllDays > 0, 'the scaled dip trips the daily loss limit at some tier');
  assert.equal(r.meanPaid, L.paid);
  assert.equal(r.meanPayouts, L.payouts);
  assert.equal(r.dllDaysPerRun, dllDays);
  assert.equal(r.pBreach, L.status === ACTIVE ? 0 : 1);
});

test('same seed => identical results; different seed => different results', () => {
  const src = () => makeParametricSource({ winRate: 0.45, avgWinR: 1.5, riskPerContract: 150, tradesPerDay: 2.5, costPerContract: 1.34 });
  const opts = { attempts: 3000, paRuns: 1500, seed: 11, sizes: [1, 3] };
  const a = sweep(rules, src(), opts);
  const b = sweep(rules, src(), opts);
  assert.deepEqual(a, b);
  const c = sweep(rules, src(), { ...opts, seed: 12 });
  assert.notDeepEqual(a.results[0].eval, c.results[0].eval);
});

test('positive edge raises P(pass) monotonically versus zero edge', () => {
  const base = { avgWinR: 2, avgLossR: 1, riskPerContract: 100, tradesPerDay: 2, costPerContract: 0 };
  const w0 = zeroEdgeWinRate(base.avgWinR, base.avgLossR);
  const pass = [0, 0.04, 0.08, 0.12].map(
    (dw) => simulateEval(rules, makeParametricSource({ ...base, winRate: w0 + dw }), { contracts: 3, attempts: 6000, seed: 3 }).pPass,
  );
  for (let i = 1; i < pass.length; i++) assert.ok(pass[i] > pass[i - 1], `P(pass) not increasing: ${pass.join(', ')}`);
});

test('zero-edge helper sets expectancy before costs to exactly 0', () => {
  assert.equal(zeroEdgeWinRate(1, 1), 0.5);
  assert.ok(Math.abs(zeroEdgeWinRate(2, 1) - 1 / 3) < 1e-15);
  for (const rr of [0.5, 1, 1.5, 2, 3]) {
    const p = zeroEdgeParams({ avgWinR: rr, riskPerContract: 100, costPerContract: 2 });
    const src = makeParametricSource(p);
    assert.ok(Math.abs(src.expectancyBeforeCosts) < 1e-9, `rr ${rr}: ${src.expectancyBeforeCosts}`);
    assert.ok(Math.abs(src.expectancyPerContract + 2) < 1e-9);
  }
});

test('eval size is capped at the evaluation maximum (minis and micros)', () => {
  const r = simulateEval(rules, coinFlip(), { contracts: 99, attempts: 50 });
  assert.equal(r.contracts, E.maxContractsMini);
  assert.equal(r.capped, true);
  const m = simulateEval(rules, coinFlip(), { contracts: 99, attempts: 50, unit: 'micro' });
  assert.equal(m.contracts, E.maxContractsMini * rules.microsPerMini);
});

test('PA simulation: a sure-win strategy collects every payout and never breaches', () => {
  // +$1,000 per trade at 2 contracts: every payout request is limited by its per-request cap.
  const src = makeParametricSource({ winRate: 1, avgWinR: 1, riskPerContract: 500, mfeOnLosersR: 0, maeOnWinnersR: 0, tradesPerDay: 2 });
  const r = simulatePa(rules, src, { contracts: 2, paRuns: 200, horizonDays: 120, seed: 5 });
  assert.equal(r.pPayout, 1);
  assert.equal(r.pBreach, 0);
  assert.equal(r.meanPayouts, PO.maxPayouts);
  assert.equal(r.meanPaid, PO.maxPerRequest.slice(0, PO.maxPayouts).reduce((a, b) => a + b, 0));
  assert.equal(r.pAllPayouts, 1);
});

test('PA simulation: a sure-loss strategy breaches before any payout', () => {
  const src = makeParametricSource({ winRate: 0, avgWinR: 1, riskPerContract: 150, tradesPerDay: 4 });
  const r = simulatePa(rules, src, { contracts: 2, paRuns: 200, horizonDays: 120, seed: 5 });
  assert.equal(r.pPayout, 0);
  assert.equal(r.pBreachBeforeFirstPayout, 1);
  assert.ok(r.dllDaysPerRun > 0, 'daily loss limit pauses sessions along the way');
});

test('runSize combines eval and PA per attempt; sweep picks the best sizes', () => {
  const src = makeParametricSource({ winRate: 0.4, avgWinR: 2, riskPerContract: 100, tradesPerDay: 2, costPerContract: 1.34 });
  const one = runSize(rules, src, { contracts: 2, attempts: 2000, paRuns: 1000, fee: 100 });
  assert.ok(Math.abs(one.combined.pPassAndPayout - one.eval.pPass * one.pa.pPayout) < 1e-12);
  assert.ok(Math.abs(one.combined.expectedPaidPerAttempt - one.eval.pPass * one.pa.meanPaid) < 1e-9);
  assert.ok(Math.abs(one.combined.paidPerFee - one.combined.expectedPaidPerAttempt / 100) < 1e-12);
  assert.ok(Math.abs(one.eval.feesPerPass - 100 / one.eval.pPass) < 1e-9);
  const s = sweep(rules, src, { attempts: 2000, paRuns: 1000, fee: 100 });
  assert.deepEqual(s.sizes, [1, 2, 3, 4, 5, 6]);
  const maxPass = Math.max(...s.results.map((r) => r.eval.pPass));
  assert.equal(s.results.find((r) => r.contracts === s.best.pass.contracts).eval.pPass, maxPass);
  const maxPaid = Math.max(...s.results.map((r) => r.combined.expectedPaidPerAttempt));
  assert.equal(s.best.payoutPerFee.expectedPaidPerAttempt, maxPaid);
  const evalOnly = sweep(rules, src, { attempts: 500, mode: 'eval', sizes: [1, 2] });
  assert.equal(evalOnly.results[0].pa, null);
  assert.equal(evalOnly.best.payoutPerFee, null);
});

test('empirical source bootstraps whole days and keeps intraday order', () => {
  const t = (dayKey, n, pnlPer) => ({ dayKey, tradeNo: n, exitTime: new Date(`${dayKey}T15:00:00Z`).getTime() + n, pnlPer, mfePer: Math.max(pnlPer, 0), maePer: Math.min(pnlPer, 0) });
  const trades = [t('2024-01-03', 4, 50), t('2024-01-02', 2, -20), t('2024-01-02', 1, 10), t('2024-01-02', 3, 30)];
  const days = groupTradesByDay(trades);
  assert.deepEqual(days.map((d) => d.dayKey), ['2024-01-02', '2024-01-03']);
  assert.deepEqual(days[0].trades.map((x) => x.tradeNo), [1, 2, 3]);
  const src = makeEmpiricalSource(trades);
  const rng = mulberry32(9);
  const seen = new Set();
  for (let i = 0; i < 200; i++) {
    const n = src.sampleDay(rng);
    const pnls = Array.from({ length: n }, (_, k) => src.buf[src.off + 3 * k]);
    seen.add(pnls.join(','));
  }
  assert.deepEqual([...seen].sort(), ['10,-20,30', '50']);
});

test('empirical source draws sessions without trades at their historical frequency', () => {
  // One trade every Monday for 4 weeks: 16 weekday sessions from the first to the last Monday.
  const t = (dayKey, n) => ({ dayKey, tradeNo: n, exitTime: new Date(`${dayKey}T15:00:00Z`), pnlPer: 400, mfePer: 400, maePer: 0 });
  const mondays = ['2024-01-01', '2024-01-08', '2024-01-15', '2024-01-22'].map(t);
  const src = makeEmpiricalSource(mondays);
  assert.equal(src.days, 4);
  assert.equal(src.sessions, 16);
  assert.equal(src.activeShare, 0.25);
  assert.equal(src.tradesPerDay, 0.25);
  assert.equal(src.tradesPerActiveDay, 1);
  const rng = mulberry32(4);
  let idle = 0;
  const N = 8000;
  for (let i = 0; i < N; i++) if (src.sampleDay(rng) === 0) idle++;
  assert.ok(Math.abs(idle / N - 0.75) < 0.02, `idle share ${idle / N}`);
  // A trade on a weekend day (session roll off) still makes that day a session.
  assert.equal(makeEmpiricalSource([t('2024-01-05', 1), t('2024-01-07', 2), t('2024-01-08', 3)]).sessions, 3);
});

test('sparse strategy: Monte Carlo pass odds match the binomial count of trades per access window', () => {
  // +$400 every Monday for a year, never dips: a pass needs 8 trades inside one access window.
  const keys = Array.from({ length: 52 }, (_, i) => addDays('2024-01-01', 7 * i));
  assert.ok(keys.every((k) => weekday(k) === 1));
  const trades = keys.map((dayKey, i) => ({ dayKey, tradeNo: i + 1, exitTime: new Date(`${dayKey}T15:00:00Z`), pnlPer: 400, mfePer: 400, maePer: 0 }));
  const src = makeEmpiricalSource(trades);
  const p = src.activeShare;
  const need = Math.ceil(E.profitTarget / 400);
  const choose = (n, k) => {
    let c = 1;
    for (let i = 1; i <= k; i++) c = (c * (n - k + i)) / i;
    return c;
  };
  const atLeast = (n) => {
    let s = 0;
    for (let k = need; k <= n; k++) s += choose(n, k) * p ** k * (1 - p) ** (n - k);
    return s;
  };
  const budgets = evalSessionBudgets(rules);
  const exact = budgets.reduce((a, n) => a + atLeast(n), 0) / budgets.length;
  const r = simulateEval(rules, src, { contracts: 1, attempts: 20000, seed: 3 });
  assert.equal(r.pBreach, 0);
  assert.ok(Math.abs(r.pPass - exact) < 4 * Math.sqrt((exact * (1 - exact)) / r.attempts) + 1e-9, `P(pass) ${r.pPass} vs ${exact}`);
  assert.ok(r.pExpire > 0.85, `P(expire) ${r.pExpire}`);
  // The replay agrees: 8 Mondays never fit in 30 calendar days.
  const h = replayEval(rules, trades, { contracts: 1 });
  assert.equal(h.passed, 0);
  assert.ok(h.expired >= 10);
});

test('evaluation session budget comes from rules.json accessDays', () => {
  assert.deepEqual(evalSessionBudgets(rules), [22, 22, 22, 22, 21]);
  assert.deepEqual(evalSessionBudgets(rules, 15), [15]);
  // +$137 a session passes on session 22 exactly: only windows that start Monday..Thursday hold 22.
  const src = makeParametricSource({ winRate: 1, avgWinR: 1, riskPerContract: 137, maeOnWinnersR: 0, tradesPerDay: 1 });
  const r = simulateEval(rules, src, { contracts: 1, attempts: 20000, seed: 9 });
  assert.ok(Math.abs(r.pPass - 0.8) < 4 * r.pPassStdErr, `P(pass) ${r.pPass}`);
  assert.equal(r.medianDaysToPass, 22);
  assert.equal(simulateEval(rules, src, { contracts: 1, attempts: 200, tradingDays: 21 }).pPass, 0);
  const longer = structuredClone(rules);
  longer.evaluation.accessDays = 60;
  assert.deepEqual(evalSessionBudgets(longer), [44, 44, 43, 42, 42]);
  assert.equal(simulateEval(longer, src, { contracts: 1, attempts: 200 }).pPass, 1);
});

test('historical replay runs back-to-back attempts through the real trade order', () => {
  const mk = (i, dayKey, pnlPer) => ({ tradeNo: i, dayKey, exitTime: new Date(`${dayKey}T15:00:00Z`), pnlPer, mfePer: Math.max(0, pnlPer), maePer: Math.min(0, pnlPer) });
  const trades = [
    mk(1, '2024-01-02', 1000),
    mk(2, '2024-01-03', 1000),
    mk(3, '2024-01-04', 1000), // attempt 1 passes (+3000)
    mk(4, '2024-01-05', -1000),
    mk(5, '2024-01-08', -1000), // attempt 2 breaches (touches 48000)
    mk(6, '2024-01-09', 100), // attempt 3 starts 2024-01-09 ...
    mk(7, '2024-02-08', 100), // ... 30 calendar days later: expired, attempt 4 starts here
  ];
  const r = replayEval(rules, trades, { contracts: 1 });
  assert.deepEqual(r.attempts.map((a) => a.status), ['PASSED', 'BREACHED', 'EXPIRED', 'OPEN']);
  assert.equal(r.passRate, 1 / 3);
});

test('historical replay: the next attempt starts at the session after the last one ended, not at the next trade', () => {
  const mk = (i, dayKey, pnlPer) => ({ tradeNo: i, dayKey, exitTime: new Date(`${dayKey}T15:00:00Z`), pnlPer, mfePer: 0, maePer: Math.min(0, pnlPer) });
  // Pass on Tue 01-02; attempt 2 starts Wed 01-03 and expires at 02-02 before the 02-05 trade.
  const r = replayEval(rules, [mk(1, '2024-01-02', 3000), mk(2, '2024-01-29', 1500), mk(3, '2024-02-05', 1500)], { contracts: 1 });
  assert.deepEqual(
    r.attempts.map((a) => [a.startDay, a.endDay, a.status, a.trades]),
    [
      ['2024-01-02', '2024-01-02', 'PASSED', 1],
      ['2024-01-03', '2024-02-02', 'EXPIRED', 1],
      ['2024-02-02', '2024-02-05', 'OPEN', 1],
    ],
  );
  // Idle stretches expire attempts with no trades; a trade later in the session of a pass is not traded.
  const g = replayEval(rules, [mk(1, '2024-01-02', 3000), mk(2, '2024-01-02', 500), mk(3, '2024-03-15', 100)], { contracts: 1 });
  assert.deepEqual(
    g.attempts.map((a) => [a.startDay, a.endDay, a.status, a.trades]),
    [
      ['2024-01-02', '2024-01-02', 'PASSED', 1],
      ['2024-01-03', '2024-02-02', 'EXPIRED', 0],
      ['2024-02-02', '2024-03-04', 'EXPIRED', 0], // 02-02 + 30 days = Sun 03-03 -> next session Mon 03-04
      ['2024-03-04', '2024-03-15', 'OPEN', 1],
    ],
  );
  assert.equal(g.skippedTrades, 1);
});

test('rSpread keeps the mean trade, varies 1R per trade, and rSpread 0 is the exact model', () => {
  const base = { winRate: 0.4, avgWinR: 2, riskPerContract: 100, tradesPerDay: 1 };
  const draw = (p, n, seed) => {
    const src = makeParametricSource(p);
    let s = seed >>> 0;
    const rng = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
    const out = [];
    for (let i = 0; i < n; i++) {
      const k = src.sampleDay(rng);
      for (let j = 0; j < k; j++) out.push(src.buf[3 * j]);
    }
    return out;
  };
  const fixed = draw({ ...base }, 2000, 7);
  const zero = draw({ ...base, rSpread: 0 }, 2000, 7);
  assert.deepEqual(zero, fixed, 'rSpread 0 must match the default exactly (no extra random draw)');
  assert.ok(fixed.every((x) => x === 200 || x === -100));
  const spread = draw({ ...base, rSpread: 0.5 }, 200000, 11);
  const mean = spread.reduce((a, b) => a + b, 0) / spread.length;
  // expectancy 0.4*200 - 0.6*100 = 20; sd per trade ~150, so 4 standard errors ~1.4
  assert.ok(Math.abs(mean - 20) < 1.5, `mean ${mean} should be ~20`);
  assert.ok(spread.some((x) => x > 0 && x !== 200) && spread.some((x) => x < 0 && x !== -100));
  assert.ok(spread.every((x) => (x > 0 ? x >= 100 && x <= 300 : x >= -150 && x <= -50)));
  assert.throws(() => makeParametricSource({ ...base, rSpread: 1 }), /rSpread/);
});
