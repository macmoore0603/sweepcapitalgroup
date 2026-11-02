import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  loadTradeifyRules,
  validateTradeifyRules,
  resolvePlan,
  makeFundedLedger,
  stepTrade,
  closeTrade,
  startDay,
  endDay,
  payoutCheck,
  contractCap,
  balance,
  simulateFunded,
  replayFunded,
  fundedSizes,
  flatTimeViolations,
  microscalpingRule,
  microscalpingCheck,
  finalBalance,
  ACTIVE,
  BREACHED,
} from '../tradeify.mjs';
import { makeEmpiricalSource, makeParametricSource } from '../sim.mjs';
import { run, tradeifyRuleLines } from '../cli.mjs';

const rules = loadTradeifyRules();
const S = rules.startBalance;
const D = rules.drawdown;

/** One session of closed trades (no excursions); returns the payout requested at the close. */
function day(L, ...pnls) {
  startDay(L, L.sessions + 1);
  for (const x of pnls) closeTrade(L, x);
  return endDay(L);
}
/** One session per entry; returns the payouts requested. */
const days = (L, list) => list.map((x) => day(L, x));
const clone = (patch) => {
  const r = structuredClone(rules);
  patch(r);
  return validateTradeifyRules(r);
};
const allTrueExcept = (checks, names) => {
  for (const [k, v] of Object.entries(checks)) assert.equal(v, !names.includes(k), `check ${k}`);
};

test('rules file loads and matches the spec numbers', () => {
  assert.equal(S, 50000);
  assert.equal(D.amount, 2000);
  assert.equal(D.lockTriggerEodBalance, 52100);
  assert.equal(D.lockedFloor, 50100);
  assert.equal(rules.split, 0.9);
  assert.equal(rules.session.flatByEt, '16:45');
  assert.throws(() => clone((r) => (r.plans.growth.legacy.newThing = 1)), /not modelled/);
  assert.throws(() => clone((r) => delete r.drawdown.lockedFloor), /lockedFloor/);
  assert.throws(() => clone((r) => (r.plans.lightning.payout.type = 'growth')), /payout.type/);
  const g = resolvePlan(rules, 'growth', { legacy: true });
  assert.equal(g.maxContractsMini, 5);
  assert.equal(g.payout.minBalance, 52100);
  assert.deepEqual(g.payout.caps, rules.plans.growth.legacy.caps);
  assert.throws(() => resolvePlan(rules, 'select-flex', { legacy: true }), /no legacy/);
  assert.throws(() => resolvePlan(rules, 'growth', { boughtBefore20260901: true }), /2026-09-01/);
  assert.throws(() => resolvePlan(rules, 'nope'), /unknown plan/);
});

test('rules the planner would ignore fail validation', () => {
  for (const plan of ['select-flex', 'select-daily']) {
    assert.throws(() => clone((r) => (r.plans[plan].consistency = [0.2])), /consistency is set/, plan);
  }
  assert.throws(() => clone((r) => (r.plans.lightning.legacy.minBalance = 60000)), /legacy.minBalance is set but is not modelled/);
  assert.throws(() => clone((r) => (r.plans['select-flex'].legacy = { caps: [1000] })), /legacy.caps is set but is not modelled/);
  assert.doesNotThrow(() => clone((r) => (r.plans['select-daily'].legacy = { maxContractsMini: 3 })));
  assert.throws(() => clone((r) => (r.plans.growth.payout.capsRepeatLast = 'no')), /capsRepeatLast must be true or false/);
  assert.throws(() => clone((r) => (r.plans['select-flex'].payout.capsRepeatLast = true)), /no caps list/);
  assert.throws(() => clone((r) => (r.plans.growth.payout.dayCountResetsAfterPayout = 0)), /must be true or false/);
  assert.throws(() => clone((r) => (r.plans['select-flex'].payout.dayCountResetsAfterPayout = false)), /growth only/);
  assert.throws(() => clone((r) => (r.plans.growth.dllRaise.effective = 'same session')), /next session/);
  assert.throws(() => clone((r) => (r.fundedRules.microscalping = 'no scalping')), /fundedRules.microscalping/);
  assert.throws(() => clone((r) => (r.plans.growth.legacy.capAfterTiers = '25000')), /capAfterTiers must be a number/);
  assert.throws(() => clone((r) => (r.plans.lightning.payout.capAfterTiers = 25000)), /growth only/);
  assert.throws(() => clone((r) => (r.plans.lightning.legacy.capAfterTiers = 25000)), /legacy.capAfterTiers is set but is not modelled/);
});

test('floor starts at 48000 and moves only at end of day, never down', () => {
  const L = makeFundedLedger(rules, 'select-flex');
  assert.equal(L.floor, 48000);
  assert.equal(L.floor, S - D.amount);
  startDay(L, 1);
  stepTrade(L, 1900, 0, 0); // intraday peak of 51900, closed flat
  assert.equal(L.floor, 48000, 'an intraday peak does not move the floor');
  stepTrade(L, 1000, -100, 800);
  assert.equal(L.floor, 48000, 'nor does an intraday close');
  endDay(L); // EOD 50800
  assert.equal(L.floor, 48800);
  day(L, -500); // EOD 50300
  assert.equal(L.floor, 48800, 'never moves down');
  day(L, 1200); // EOD 51500
  assert.equal(L.floor, 49500);
  assert.equal(L.locked, false);
});

test('breach the moment net liquidation equals the floor', () => {
  const L = makeFundedLedger(rules, 'select-flex'); // no DLL
  startDay(L, 1);
  assert.equal(stepTrade(L, 0, -1999.99, 0), ACTIVE);
  assert.equal(stepTrade(L, 0, -2000, 0), BREACHED, 'net liquidation 48000 = floor');
  assert.equal(L.breachNetLiq, 48000);

  const C = makeFundedLedger(rules, 'select-flex');
  startDay(C, 1);
  assert.equal(closeTrade(C, -2000), BREACHED, 'a close at the floor breaches too');

  const T = makeFundedLedger(rules, 'select-flex');
  day(T, 1000); // EOD 51000 -> floor 49000
  startDay(T, 2);
  assert.equal(stepTrade(T, 0, -1999.99, 0), ACTIVE);
  assert.equal(stepTrade(T, 0, -2000, 0), BREACHED);

  // Growth: the floor is checked before the soft DLL at the true adverse extreme ('extreme' fill); with
  // 'limit' the platform flattens at the DLL first, so the same trade only pauses the session.
  const G = makeFundedLedger(rules, 'growth');
  startDay(G, 1);
  assert.equal(stepTrade(G, 0, -2000, -2000), BREACHED);
  const GL = makeFundedLedger(rules, 'growth', { dllFill: 'limit' });
  startDay(GL, 1);
  assert.equal(stepTrade(GL, 0, -2000, -2000), ACTIVE);
  assert.equal(balance(GL), 48750);
  assert.equal(GL.dayHalted, true);

  // The intratrade order cannot change a result: the floor does not move intraday and the favorable
  // extreme is >= 0, so only the adverse extreme can breach, under either order.
  for (const order of ['conservative', 'adverse-first']) {
    const A = makeFundedLedger(rules, 'select-flex', { order });
    startDay(A, 1);
    assert.equal(stepTrade(A, 3000, -2000, 500), BREACHED, order);
    assert.equal(A.breachNetLiq, 48000, order);
  }
  const src = () =>
    makeParametricSource({ winRate: 0.45, avgWinR: 2, riskPerContract: 300, tradesPerDay: 3, costPerContract: 1.34, rSpread: 0.5 });
  for (const plan of ['growth', 'select-flex', 'select-daily', 'lightning']) {
    const opts = { contracts: 3, runs: 300, horizonDays: 60, seed: 4 };
    const c = simulateFunded(rules, plan, src(), { ...opts, order: 'conservative' });
    assert.ok(c.pBreach > 0, `${plan}: some accounts breach`);
    assert.deepEqual(simulateFunded(rules, plan, src(), { ...opts, order: 'adverse-first' }), c, plan);
  }
});

test('floor locks at 50100 once an EOD balance reaches 52100, forever', () => {
  const L = makeFundedLedger(rules, 'select-flex');
  day(L, 2099.99); // EOD 52099.99
  assert.equal(L.locked, false);
  assert.equal(L.floor, 50099.99);
  day(L, 0.01); // EOD 52100
  assert.equal(L.locked, true);
  assert.equal(L.lockedBy, 'eod');
  assert.equal(L.floor, 50100);
  day(L, 5000); // EOD 57100
  assert.equal(L.floor, 50100, 'locked floor never trails again');
  startDay(L, 4);
  assert.equal(stepTrade(L, 0, -6999.99, -6000), ACTIVE); // net liq 50100.01
  assert.equal(closeTrade(L, -1000), BREACHED); // 50100 = floor
});

test('a payout request locks the floor immediately', () => {
  const L = makeFundedLedger(rules, 'select-flex');
  const paid = days(L, [150, 150, 150, 150, 150]); // EOD 50750, floor 48750, not locked by EOD
  assert.deepEqual(paid, [0, 0, 0, 0, 375]);
  assert.equal(L.locked, true);
  assert.equal(L.lockedBy, 'payout');
  assert.equal(L.floor, 50100);
  assert.equal(balance(L), 50375);
  assert.equal(L.requested, 375);
  assert.equal(L.received, 337.5);
  assert.equal(L.payoutHistory[0].balanceAfter, 50375);
});

test('daily loss limit: soft pause for the session, resume next session', () => {
  const L = makeFundedLedger(rules, 'growth');
  assert.equal(L.dll, 1250);
  startDay(L, 1);
  stepTrade(L, 100, -1249.99, -1249.99);
  assert.equal(L.dayHalted, false, '-1249.99 is above the limit');
  stepTrade(L, 0, -0.01, -0.01); // session P&L reaches -1250 at the adverse extreme
  assert.equal(L.dayHalted, true);
  assert.equal(L.status, ACTIVE, 'the account stays open');
  const before = balance(L);
  stepTrade(L, 500, 0, 500);
  assert.equal(balance(L), before, 'no more trades this session');
  assert.equal(L.dllSkippedTrades, 1);
  endDay(L);
  assert.equal(L.dllDays, 1);
  startDay(L, 2);
  assert.equal(L.dayHalted, false);
  stepTrade(L, 500, 0, 500);
  assert.equal(balance(L), before + 500, 'trading resumes next session');

  // The flatten books the adverse extreme (default 'extreme' fill), not the trade's close.
  const E = makeFundedLedger(rules, 'growth');
  startDay(E, 1);
  stepTrade(E, 100, -1300, 400, 2);
  assert.equal(balance(E), S - 1302);
  assert.equal(E.dayHalted, true);
});

test('DLL rises to 2000 after a 53000 close for Growth and Lightning, not for Select Daily', () => {
  for (const plan of ['growth', 'lightning']) {
    const L = makeFundedLedger(rules, plan);
    assert.equal(L.dll, rules.plans[plan].dailyLossLimit);
    day(L, 2999.99); // EOD 52999.99
    assert.equal(L.dll, 1250, `${plan}: below 53000`);
    day(L, 0.01); // EOD 53000
    assert.equal(L.dll, 2000, `${plan}: from the next session`);
    day(L, -500); // EOD 52500: modelled as permanent
    assert.equal(L.dll, 2000, `${plan}: permanent`);
    startDay(L, 4);
    stepTrade(L, 0, -1999.99, -1999.99); // net liquidation 50500.01, above the locked 50100 floor
    assert.equal(L.dayHalted, false);
    stepTrade(L, 0, -0.01, -0.01);
    assert.equal(L.dayHalted, true);
  }
  const SD = makeFundedLedger(rules, 'select-daily');
  assert.equal(SD.dll, 1000);
  day(SD, 3000); // EOD 53000 (pays out down to the 52100 buffer)
  assert.equal(SD.dll, 1000);
  assert.equal(makeFundedLedger(rules, 'select-flex').dll, null);
  const legacy = makeFundedLedger(rules, 'growth', { legacy: true });
  day(legacy, 3000);
  assert.equal(legacy.dll, null, 'legacy Growth: the DLL is removed at dllRemovedAt');
});

test('Select scaling: 2 / 3 / 4 minis from the highest EOD profit, kept once reached, next session', () => {
  for (const plan of ['select-flex', 'select-daily']) {
    const L = makeFundedLedger(rules, plan);
    assert.equal(contractCap(L), 2);
    assert.equal(contractCap(L, 'micro'), 20);
    day(L, 1499.99);
    assert.equal(contractCap(L), 2, `${plan}: 1499.99`);
    startDay(L, 2);
    closeTrade(L, 0.01);
    assert.equal(contractCap(L), 2, `${plan}: not intraday`);
    endDay(L); // EOD profit 1500
    assert.equal(contractCap(L), 3, `${plan}: 1500`);
    day(L, -1000); // profit 500
    assert.equal(contractCap(L), 3, `${plan}: kept after a drop`);
    day(L, 1499.99); // profit 1999.99
    assert.equal(contractCap(L), 3);
    day(L, 0.01); // profit 2000
    assert.equal(contractCap(L), 4, `${plan}: 2000`);
    assert.equal(contractCap(L, 'micro'), 40);
    day(L, -1500);
    assert.equal(contractCap(L), 4);
  }
  assert.equal(contractCap(makeFundedLedger(rules, 'growth')), 4);
  assert.equal(contractCap(makeFundedLedger(rules, 'growth', { legacy: true }), 'micro'), 50);
  assert.equal(contractCap(makeFundedLedger(rules, 'lightning', { legacy: true })), 5);
});

test('Growth: 5 days strictly above $150 (a day of exactly $150 does not count)', () => {
  const L = makeFundedLedger(rules, 'growth');
  days(L, [800, 800, 800, 800]); // 53200, 4 qualifying days
  assert.equal(day(L, 150), 0, 'exactly 150 does not qualify');
  assert.equal(L.qualDays, 4);
  allTrueExcept(payoutCheck(L).checks, ['days']);
  assert.equal(day(L, 150.01), 1500);
  assert.equal(L.qualDays, 0, 'day count resets');
  assert.equal(L.cycleProfit, 0);
});

test('Growth: largest day at most 35% of profit since the last payout', () => {
  const ok = makeFundedLedger(rules, 'growth');
  assert.deepEqual(days(ok, [1050, 487.5, 487.5, 487.5, 487.5]), [0, 0, 0, 0, 1500], 'exactly 35%');
  const bad = makeFundedLedger(rules, 'growth');
  assert.deepEqual(days(bad, [1050.01, 487.5, 487.5, 487.5, 487.5]), [0, 0, 0, 0, 0], 'just over 35%');
  allTrueExcept(payoutCheck(bad).checks, ['consistency']);
});

test('Growth: balance of at least 53000 (legacy 52100)', () => {
  const L = makeFundedLedger(rules, 'growth');
  assert.deepEqual(days(L, [600, 600, 600, 600, 599.99]), [0, 0, 0, 0, 0]); // 52999.99
  allTrueExcept(payoutCheck(L).checks, ['balance']);
  assert.equal(day(L, 0.01), 1500, '53000 pays (5 qualifying days kept)');
  const legacy = makeFundedLedger(rules, 'growth', { legacy: true });
  assert.deepEqual(days(legacy, [420, 420, 420, 420, 419.99]), [0, 0, 0, 0, 0]); // 52099.99
  assert.equal(day(legacy, 0.01), 1500, 'legacy: 52100 pays');
});

test('Growth: $500 minimum and payout policy min', () => {
  const below = makeFundedLedger(clone((r) => (r.plans.growth.payout.caps = [499.99])), 'growth');
  assert.deepEqual(days(below, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 0]);
  allTrueExcept(payoutCheck(below).checks, ['minPayout']);
  const at = makeFundedLedger(clone((r) => (r.plans.growth.payout.caps = [500])), 'growth');
  assert.deepEqual(days(at, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 500]);
  const min = makeFundedLedger(rules, 'growth', { payout: 'min' });
  assert.deepEqual(days(min, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 500]);
  assert.equal(min.received, 450);
});

test('Growth: cap tiers 1500 / 2000 / 2500 / 3000 then 3000, and the day count resets', () => {
  const L = makeFundedLedger(rules, 'growth');
  const paid = [];
  paid.push(...days(L, [600, 600, 600, 600, 600]).filter(Boolean)); // 53000 -> 51500
  assert.deepEqual(days(L, [400, 400, 400, 400]), [0, 0, 0, 0], '4 new days are not enough after a payout');
  allTrueExcept(payoutCheck(L).checks, ['days']);
  paid.push(day(L, 400)); // 53500 -> 2000
  paid.push(...days(L, [400, 400, 400, 400, 400]).filter(Boolean)); // 53500 -> 2500
  paid.push(...days(L, [600, 600, 600, 600, 600]).filter(Boolean)); // 54000 -> 3000
  paid.push(...days(L, [600, 600, 600, 600, 600]).filter(Boolean)); // 54000 -> 3000
  assert.deepEqual(paid, [1500, 2000, 2500, 3000, 3000]);
  assert.deepEqual(rules.plans.growth.payout.caps, [1500, 2000, 2500, 3000]);
  assert.equal(L.requested, 12000);
  assert.equal(L.received, 10800);
  // Amount is also capped at balance - floor - 0.01.
  const C = makeFundedLedger(clone((r) => (r.plans.growth.payout.caps = [5000])), 'growth');
  assert.deepEqual(days(C, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 2899.99]);
  assert.equal(balance(C), 50100.01);
});

test('legacy Growth: capAfterTiers caps the payouts after the 6th tier (else the last tier repeats)', () => {
  const run7 = (r) => {
    const L = makeFundedLedger(r, 'growth', { legacy: true });
    const paid = [];
    while (paid.length < 7) paid.push(...days(L, [2000, 2000, 2000, 2000, 2000]).filter(Boolean));
    return paid;
  };
  const tiers = rules.plans.growth.legacy.caps;
  // The shipped rules carry the verified $25,000 limit after the 6th legacy payout.
  assert.equal(rules.plans.growth.legacy.capAfterTiers, 25000);
  assert.deepEqual(run7(rules), [...tiers, 25000]);
  const noCap = clone((r) => delete r.plans.growth.legacy.capAfterTiers);
  assert.deepEqual(run7(noCap), [...tiers, tiers[tiers.length - 1]], 'without capAfterTiers the last tier repeats');
  const withCap = clone((r) => (r.plans.growth.legacy.capAfterTiers = 25000));
  assert.deepEqual(run7(withCap), [...tiers, 25000]);
  assert.equal(resolvePlan(withCap, 'growth').payout.capAfterTiers, undefined, 'legacy only');
  assert.match(tradeifyRuleLines(withCap, resolvePlan(withCap, 'growth', { legacy: true }), 'mini')[1], /\$3,000, then \$25,000, balance - floor/);
  // Still bounded by balance - floor - 0.01.
  const M = makeFundedLedger(withCap, 'growth', { legacy: true });
  for (let i = 0; i < 6; i++) days(M, [2000, 2000, 2000, 2000, 2000]);
  assert.equal(M.payouts, 6);
  assert.equal(balance(M), 97000);
  day(M, -26000); // 71000, floor locked at 50100
  const c = payoutCheck(M);
  assert.equal(c.n, 7);
  assert.equal(c.cap, 25000);
  assert.equal(c.maxAmount, 20899.99, 'min(25000, 71000 - 50100 - 0.01)');
});

test('Select Flex: 5 winning days >= $150, 50% of total profit, caps, $250 minimum', () => {
  const L = makeFundedLedger(rules, 'select-flex');
  assert.deepEqual(days(L, [150, 150, 150, 150, 149.99]), [0, 0, 0, 0, 0]);
  allTrueExcept(payoutCheck(L).checks, ['days']);
  assert.equal(day(L, 150), 449.99, '5th winning day: 50% of 899.99, rounded down to the cent');

  const cap = makeFundedLedger(rules, 'select-flex');
  assert.deepEqual(days(cap, [2000, 2000, 2000, 2000, 2000]), [0, 0, 0, 0, 2500]);
  const old = makeFundedLedger(rules, 'select-flex', { boughtBefore20260901: true });
  assert.deepEqual(days(old, [2000, 2000, 2000, 2000, 2000]), [0, 0, 0, 0, 3000]);

  const min = makeFundedLedger(rules, 'select-flex');
  assert.deepEqual(days(min, [-250, 150, 150, 150, 150, 150]), [0, 0, 0, 0, 0, 250], 'total 500 -> 250');
  const under = makeFundedLedger(rules, 'select-flex');
  assert.deepEqual(days(under, [-250.02, 150, 150, 150, 150, 150]), [0, 0, 0, 0, 0, 0], 'total 499.98 -> 249.99');
  allTrueExcept(payoutCheck(under).checks, ['minPayout']);
});

test('Select Flex: from payout 2 the profit since the last payout must be positive', () => {
  const L = makeFundedLedger(rules, 'select-flex');
  assert.deepEqual(days(L, [2000, 2000, 2000, 2000, 2000]), [0, 0, 0, 0, 2500]); // 57500
  assert.equal(L.qualDays, 0, 'winning days reset');
  assert.deepEqual(days(L, [-760, 150, 150, 150, 150, 150]), [0, 0, 0, 0, 0, 0]); // cycle -10
  const c = payoutCheck(L);
  assert.equal(c.n, 2);
  allTrueExcept(c.checks, ['cycleProfit']);
  assert.equal(day(L, 10.01), 2500, 'cycle +0.01');
});

test('Select Daily: 52100 buffer, 2x cycle profit, caps 1250 / 1000, $250 minimum, positive cycle', () => {
  const B = makeFundedLedger(rules, 'select-daily');
  assert.equal(day(B, 2349.99), 0); // 52349.99 -> 249.99
  allTrueExcept(payoutCheck(B).checks, ['minPayout']);
  assert.equal(day(B, 0.01), 250); // 52350
  assert.equal(balance(B), 52100);

  const L = makeFundedLedger(rules, 'select-daily');
  assert.equal(day(L, 5000), 1250, 'cap 1250'); // 55000 -> 53750
  assert.equal(day(L, 130), 260, '2x cycle profit');
  assert.equal(payoutCheck(L).eligible, false, 'at most one payout per day');
  assert.equal(day(L, 124.99), 0); // 249.98
  allTrueExcept(payoutCheck(L).checks, ['minPayout']);
  assert.equal(day(L, -250), 0); // cycle -125.01
  allTrueExcept(payoutCheck(L).checks, ['cycleProfit', 'minPayout']);
  assert.equal(day(L, 125.01), 0, 'cycle 0 is not positive');
  assert.equal(payoutCheck(L).checks.cycleProfit, false);
  assert.equal(day(L, 200), 400);
  assert.equal(L.payouts, 3);

  const old = makeFundedLedger(rules, 'select-daily', { boughtBefore20260901: true });
  assert.equal(day(old, 5000), 1000, 'cap 1000 for accounts bought before 2026-09-01');
});

/** Run the given sessions (one list per payout cycle); returns the payouts requested. */
function lightningTo(L, cycles) {
  const paid = [];
  for (const list of cycles) paid.push(...days(L, list).filter(Boolean));
  return paid;
}

test('Lightning: goal 3000 then 2000 of new profit, consistency 20 / 25 / 30%, caps, $1000 minimum', () => {
  const L = makeFundedLedger(rules, 'lightning');
  assert.deepEqual(days(L, [599.99, 599.99, 599.99, 599.99, 599.99]), [0, 0, 0, 0, 0]); // 2999.95
  allTrueExcept(payoutCheck(L).checks, ['goal']);
  assert.equal(day(L, 0.05), 2000, 'goal 3000 reached'); // 53000 -> 51000
  assert.deepEqual(days(L, [499.99, 499.99, 499.99, 499.99]), [0, 0, 0, 0]); // 1999.96 of new profit
  allTrueExcept(payoutCheck(L).checks, ['goal']);
  assert.equal(day(L, 0.04), 2000, 'goal 2000 of new profit'); // 53000 -> 51000
  assert.deepEqual(days(L, [600, 600, 400, 400]), [0, 0, 0, 2000], 'payout 3: largest day exactly 30%'); // -> 51000
  assert.deepEqual(days(L, [500, 500, 500, 500]), [0, 0, 0, 2500], 'payout 4: cap 2500'); // 53000 -> 50500
  assert.deepEqual(days(L, [550, 550, 550, 550]), [0, 0, 0, 2500], 'then 2500'); // 52700 -> 50200
  assert.equal(L.payouts, 5);
  assert.deepEqual(rules.plans.lightning.payout.caps, [2000, 2000, 2000, 2500]);
  assert.deepEqual(rules.plans.lightning.payout.profitGoals, [3000, 2000]);
  assert.deepEqual(rules.plans.lightning.consistency, [0.2, 0.25, 0.3]);

  const c20 = makeFundedLedger(rules, 'lightning');
  assert.deepEqual(days(c20, [600.01, 600, 600, 600, 600]), [0, 0, 0, 0, 0], 'payout 1: over 20%');
  allTrueExcept(payoutCheck(c20).checks, ['consistency']);

  const c25 = makeFundedLedger(rules, 'lightning');
  assert.deepEqual(lightningTo(c25, [[600, 600, 600, 600, 600]]), [2000], 'payout 1: largest day exactly 20%');
  assert.deepEqual(days(c25, [500.01, 500, 500, 500]), [0, 0, 0, 0], 'payout 2: over 25%');
  allTrueExcept(payoutCheck(c25).checks, ['consistency']);

  const c30 = makeFundedLedger(rules, 'lightning');
  lightningTo(c30, [[600, 600, 600, 600, 600], [500, 500, 500, 500]]);
  assert.deepEqual(days(c30, [600.01, 600, 400, 400]), [0, 0, 0, 0], 'payout 3: over 30%');
  allTrueExcept(payoutCheck(c30).checks, ['consistency']);

  const legacy = makeFundedLedger(rules, 'lightning', { legacy: true });
  lightningTo(legacy, [[600, 600, 600, 600, 600]]);
  assert.deepEqual(days(legacy, [500, 500, 500, 500]), [0, 0, 0, 0], 'legacy: 20% for every payout');

  const below = makeFundedLedger(clone((r) => (r.plans.lightning.payout.caps = [999.99])), 'lightning');
  assert.deepEqual(days(below, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 0]);
  allTrueExcept(payoutCheck(below).checks, ['minPayout']);
  const at = makeFundedLedger(clone((r) => (r.plans.lightning.payout.caps = [1000])), 'lightning');
  assert.deepEqual(days(at, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 1000]);
});

// Weekday sessions 2024-01-01 (Mon) .. 2024-01-05 (Fri).
const mk = (i, dayKey, contracts, pnlPer, mfePer, maePer, hhmm = '15:00') => ({
  tradeNo: i + 1,
  dayKey,
  entryTime: new Date(`${dayKey}T14:00:00Z`),
  exitTime: new Date(`${dayKey}T${hhmm}:00Z`),
  contracts,
  pnl: pnlPer * contracts,
  pnlPer,
  mfePer,
  maePer,
});

test('risk scaling caps each trade at the plan cap (and at the Select scaling tier)', () => {
  const trades = [mk(0, '2024-01-02', 1, -450, 0, -450)];
  const risk = { scaling: 'risk', contracts: 10 };
  const g = replayFunded(rules, 'growth', trades, risk);
  assert.equal(g.last.balance, S - 4 * 450, 'growth: 10 wanted, 4 minis traded');
  assert.equal(g.last.status, 'OPEN');
  assert.equal(g.cappedTradeShare, 1);
  assert.equal(g.dllDays, 1, '-1800 is past the 1250 DLL: flattened, account open');
  const f = replayFunded(rules, 'select-flex', trades, risk);
  assert.equal(f.last.balance, S - 2 * 450, 'select-flex: first tier 2 minis');
  const u = replayFunded(rules, 'growth', trades, { ...risk, contracts: 3 });
  assert.equal(u.last.balance, S - 3 * 450, 'under the cap: as traded x k');
  assert.equal(u.cappedTradeShare, 0);
  const m = replayFunded(rules, 'growth', trades, { ...risk, unit: 'micro' });
  assert.equal(m.breached, 1, 'micros: 10 x -450 is under the 40-micro cap and breaches');

  const src = makeEmpiricalSource(trades, { scaling: 'risk' });
  const sim = simulateFunded(rules, 'growth', src, { contracts: 10, runs: 50, horizonDays: 1, seed: 1 });
  assert.equal(sim.cappedTradeShare, 1);
  assert.equal(sim.pBreach, 0);
  assert.equal(sim.meanEndBalance, S - 4 * 450);
  assert.deepEqual(fundedSizes(rules, 'growth', src), [1, 2, 3, 4]);
  assert.deepEqual(fundedSizes(rules, 'growth', makeEmpiricalSource(trades)), [1, 2, 3, 4]);
});

test('a breached account ends at its net liquidation at the breach, not the pre-trade balance', () => {
  const trades = [mk(0, '2024-01-02', 1, -100, 0, -2500)]; // intraday breach at 47500, closed at -100
  const sim = simulateFunded(rules, 'select-flex', makeEmpiricalSource(trades), { contracts: 1, runs: 10, horizonDays: 1 });
  assert.equal(sim.pBreach, 1);
  assert.equal(sim.meanEndBalance, 47500);
  const rp = replayFunded(rules, 'select-flex', trades, { contracts: 1 });
  assert.equal(rp.last.status, BREACHED);
  assert.equal(rp.last.balance, 47500);
  assert.equal(rp.last.breachNetLiq, 47500);
  const L = makeFundedLedger(rules, 'select-flex');
  startDay(L, 1);
  stepTrade(L, 0, -2500, -100);
  assert.equal(balance(L), S, 'the open loss is never booked');
  assert.equal(finalBalance(L), 47500);
  const C = makeFundedLedger(rules, 'select-flex');
  startDay(C, 1);
  closeTrade(C, -2000);
  assert.equal(finalBalance(C), balance(C), 'a breach on the close: the balance itself');
  assert.equal(finalBalance(makeFundedLedger(rules, 'growth')), S);
});

test('replay: a breach ends the account and a fresh one starts at the next session', () => {
  const trades = [
    mk(0, '2024-01-01', 1, -2100, 0, -2100),
    mk(1, '2024-01-01', 1, 500, 500, 0, '16:00'), // same session as the breach: belongs to no account
    mk(2, '2024-01-03', 1, 300, 300, 0),
  ];
  const r = replayFunded(rules, 'select-flex', trades, { contracts: 1 });
  assert.equal(r.total, 2);
  assert.equal(r.breached, 1);
  assert.equal(r.skippedTrades, 1);
  assert.equal(r.accounts[1].startDay, '2024-01-02');
  assert.equal(r.last.balance, S + 300);
  assert.equal(r.sessions, 3);
});

test('simulateFunded is reproducible for a seed', () => {
  const src = () =>
    makeParametricSource({ winRate: 0.5, avgWinR: 1.5, riskPerContract: 100, tradesPerDay: 2, costPerContract: 1, rSpread: 0.5 });
  const opts = { contracts: 2, runs: 400, horizonDays: 60, seed: 11 };
  for (const plan of ['growth', 'select-flex', 'select-daily', 'lightning']) {
    const a = simulateFunded(rules, plan, src(), opts);
    const b = simulateFunded(rules, plan, src(), opts);
    assert.deepEqual(a, b, plan);
    assert.ok(a.pPayout > 0, `${plan} pays sometimes`);
    // Each payout's 90% is rounded to the cent.
    assert.ok(Math.abs(a.meanReceived - a.meanRequested * rules.split) <= 0.005 * a.meanPayouts + 1e-9, plan);
  }
  const c = simulateFunded(rules, 'growth', src(), { ...opts, seed: 12 });
  assert.notDeepEqual(c, simulateFunded(rules, 'growth', src(), opts));
});

test('flat-time check: exits after 16:45 ET or across the session break', () => {
  const at = (key, hhmm) => new Date(`${key}T${hhmm}:00-05:00`); // EST in January
  const t = (i, entry, exit) => ({ tradeNo: i, entryTime: entry, exitTime: exit });
  const list = [
    t(1, at('2024-01-02', '16:00'), at('2024-01-02', '16:45')), // flat at 16:45: fine
    t(2, at('2024-01-02', '16:00'), at('2024-01-02', '16:46')), // late
    t(3, at('2024-01-02', '16:20'), at('2024-01-02', '18:00')), // held across the break
    t(4, at('2024-01-02', '18:05'), at('2024-01-02', '19:00')), // next session, fine
  ];
  assert.deepEqual(flatTimeViolations(rules, list).map((x) => x.tradeNo), [2, 3]);

  // Early-close days listed by the caller use session.earlyCloseFlatByEt (12:59 ET).
  assert.equal(rules.session.earlyCloseFlatByEt, '12:59');
  const early = [
    t(5, at('2024-11-29', '12:30'), at('2024-11-29', '13:10')), // Black Friday: late
    t(6, at('2024-12-24', '12:00'), at('2024-12-24', '16:30')), // Christmas Eve: late
    t(7, at('2024-11-29', '12:00'), at('2024-11-29', '12:59')), // flat at 12:59: fine
    t(8, at('2024-11-28', '18:30'), at('2024-11-29', '12:59')), // session opened the evening before: fine
    t(9, at('2024-11-27', '12:00'), at('2024-11-27', '14:00')), // not an early-close day: fine
  ];
  assert.deepEqual(flatTimeViolations(rules, early).map((x) => x.tradeNo), [], 'no early-close days given');
  assert.deepEqual(flatTimeViolations(rules, early, undefined, ['2024-11-29', '2024-12-24']).map((x) => x.tradeNo), [5, 6]);
  const lateSecond = [{ tradeNo: 10, entryTime: at('2024-11-29', '12:00'), exitTime: new Date(at('2024-11-29', '12:59').getTime() + 1000) }];
  assert.equal(flatTimeViolations(rules, lateSecond, undefined, ['2024-11-29']).length, 1, '12:59:01 is late');
});

test('microscalping: more than 50% of trades and of gross profit from holds over 10 seconds', () => {
  assert.deepEqual(microscalpingRule(rules), { minShare: 0.5, minHoldSeconds: 10 });
  const t = (i, holdS, pnlPer, contracts = 1) => {
    const e = new Date(Date.UTC(2024, 0, 2, 15, i));
    return { tradeNo: i, entryTime: e, exitTime: new Date(e.getTime() + holdS * 1000), contracts, pnlPer, pnl: pnlPer * contracts };
  };
  const scalps = microscalpingCheck(rules, [1, 2, 3, 4, 5, 6].map((i) => t(i, 5, 700)));
  assert.equal(scalps.passes, false);
  assert.equal(scalps.longShareOfTrades, 0);
  assert.equal(scalps.longShareOfProfit, 0);

  const half = microscalpingCheck(rules, [t(1, 10, 100), t(2, 11, 100), t(3, 60, -50), t(4, 0, 300)]);
  assert.equal(half.longShareOfTrades, 0.5, '10 s exactly is not longer than 10 s');
  assert.equal(half.longShareOfProfit, 0.2);
  assert.equal(half.sameTimestamp, 1);
  assert.equal(half.passes, false, 'exactly 50% is not more than 50%');

  assert.equal(microscalpingCheck(rules, [t(1, 60, 100), t(2, 120, 100), t(3, 5, 50)]).passes, true);
  const profit = microscalpingCheck(rules, [t(1, 60, -100), t(2, 60, 10), t(3, 5, 500)]);
  assert.equal(profit.passes, false, 'most profit from a short hold');

  const sized = [t(1, 60, 100, 1), t(2, 60, 100, 1), t(3, 5, 120, 3)];
  assert.equal(microscalpingCheck(rules, sized).longShareOfProfit, 200 / 320, 'per contract');
  assert.equal(microscalpingCheck(rules, sized, { scaling: 'risk' }).longShareOfProfit, 200 / 560, 'as traded');

  const noEntry = microscalpingCheck(rules, [t(1, 60, 100), { tradeNo: 2, exitTime: new Date(), pnlPer: 50, pnl: 50 }]);
  assert.equal(noEntry.trades, 1);
  assert.equal(noEntry.unknownHold, 1);
  assert.equal(microscalpingCheck(clone((r) => delete r.fundedRules.microscalping), []), null, 'no rule in the file');
});

test('CLI: --firm tradeify options and validation', () => {
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5'];
  const out = run([...base, '--json']).data;
  assert.equal(out.planner, 'tradeify-50k');
  assert.equal(out.rules.plan, 'growth');
  assert.deepEqual(out.settings.sizes, [1, 2, 3, 4]);
  assert.equal(out.settings.payout, 'max');
  assert.equal(out.replay, null);
  assert.deepEqual(run([...base, '--unit', 'micro', '--json']).data.settings.sizes, Array.from({ length: 40 }, (_, i) => i + 1));
  assert.equal(run([...base, '--legacy', '--json']).data.settings.cap, 5);
  assert.equal(run([...base, '--plan', 'select-daily', '--select-caps-before-2026-09-01', '--json']).data.rules.effective.payout.cap, 1000);
  assert.equal(run([...base, '--mode', 'funded', '--contracts', '2', '--json']).data.results.length, 1);
  const text = run([...base, '--plan', 'lightning', '--contracts', '1,3']).text;
  assert.match(text, /FUNDED ACCOUNT/);
  assert.match(text, /Lightning 50K Funded/);
  assert.match(text, /Summary: /);
  assert.match(text, /flat by 16:45 ET \(12:59 ET on early-close days\)/);
  assert.match(text, /not modelled: minimum activity \(at least 1 trade per week\); flat time and microscalping \(checked on --trades only\)/);
  assert.doesNotMatch(text, /order conservative/);
  assert.equal(out.settings.order, undefined, '--order is not a Tradeify setting');
  assert.throws(() => run([...base, '--order', 'adverse-first']), /--order has no effect with --firm tradeify/);
  assert.throws(() => run([...base, '--order', 'conservative']), /--order has no effect/);
  assert.throws(() => run([...base, '--early-close', '2024-11-29']), /--early-close only applies with --trades/);
  const help = run(['--help']).text;
  for (const opt of ['--firm', '--plan', '--legacy', '--select-caps-before-2026-09-01', '--payout', '--runs']) assert.ok(help.includes(opt), opt);

  assert.throws(() => run(['--firm', 'nope', ...base.slice(2)]), /--firm must be/);
  assert.throws(() => run([...base, '--mode', 'eval']), /funded account only/);
  assert.throws(() => run([...base, '--mode', 'pa']), /funded account only/);
  for (const k of [['--feed', 'tradovate'], ['--attempts', '5'], ['--pa-runs', '5'], ['--days', '5'], ['--fee', '100']]) {
    assert.throws(() => run([...base, ...k]), /Apex evaluation\/PA option/, k[0]);
  }
  assert.throws(() => run([...base, '--plan', 'nope']), /unknown plan/);
  assert.throws(() => run([...base, '--plan', 'select-flex', '--legacy']), /no legacy/);
  assert.throws(() => run([...base, '--select-caps-before-2026-09-01']), /2026-09-01/);
  assert.throws(() => run([...base, '--payout', 'half']), /payout policy/);
  assert.throws(() => run([...base, '--contracts', '5']), /outside 1\.\.4/);
  assert.throws(() => run([...base, '--unit', 'micro', '--contracts', '41']), /outside 1\.\.40/);
  assert.doesNotThrow(() => run([...base, '--unit', 'micro', '--legacy', '--contracts', '50', '--json']));
  assert.throws(() => run([...base, '--sweep', '--contracts', '2']), /not both/);
  assert.throws(() => run([...base, '--runs', '0']), /--runs/);
  // Tradeify-only options are rejected for Apex.
  for (const k of [['--plan', 'growth'], ['--legacy'], ['--payout', 'max'], ['--runs', '5'], ['--select-caps-before-2026-09-01'], ['--early-close', '2024-11-29']]) {
    assert.throws(() => run(['--win', '0.5', '--rr', '1', '--risk', '100', ...k]), /only appl(y|ies) with --firm tradeify/, k[0]);
  }
});

test('CLI: --firm tradeify with a CSV replays the actual trades and flags late exits', () => {
  const dir = mkdtempSync(join(tmpdir(), 'tradeify-'));
  const lines = ['Trade #,Type,Date and time,Signal,Price USD,Position size (qty),Net P&L USD,Favorable excursion USD,Adverse excursion USD'];
  const rows = [
    ['2024-01-02 10:00', '2024-01-02 10:30', 1, 200, 250, -50],
    ['2024-01-03 16:30', '2024-01-03 16:50', 1, -100, 20, -120], // exits after 16:45 ET
    ['2024-01-04 10:00', '2024-01-04 11:00', 2, 300, 340, -40],
  ];
  rows.forEach(([a, b, q, pnl, mfe, mae], i) => {
    lines.push(`${i + 1},Entry long,${a},S,100,${q},${pnl},${mfe},${mae}`);
    lines.push(`${i + 1},Exit long,${b},S,100,${q},${pnl},${mfe},${mae}`);
  });
  const file = join(dir, 'list.csv');
  writeFileSync(file, `${lines.join('\n')}\n`);
  const out = run(['--firm', 'tradeify', '--trades', file, '--runs', '50', '--horizon', '10', '--json']).data;
  assert.equal(out.settings.scaling, 'risk');
  assert.equal(out.source.flatTimeViolations, 1);
  assert.deepEqual(out.source.flatTimeTrades, [2]);
  assert.equal(out.replay.length, out.settings.sizes.length);
  const r1 = out.replay[0];
  assert.equal(r1.contracts, 1);
  assert.equal(r1.last.balance, S + 200 - 100 + 300);
  const text = run(['--firm', 'tradeify', '--trades', file, '--runs', '50', '--horizon', '10', '--contracts', '1']).text;
  assert.match(text, /HISTORICAL REPLAY/);
  assert.match(text, /WARNING: 1 trade\(s\) \(#2\)/);
});

test('CLI: --early-close days and the microscalping check on a CSV', () => {
  const dir = mkdtempSync(join(tmpdir(), 'tradeify-'));
  const lines = ['Trade #,Type,Date and time,Signal,Price USD,Position size (qty),Net P&L USD,Favorable excursion USD,Adverse excursion USD'];
  const rows = [
    ['2024-11-29 12:30', '2024-11-29 13:10', 200, 250, -50], // after 12:59 on an early-close day
    ['2024-12-02 10:00', '2024-12-02 10:00', 300, 300, 0], // same timestamp: a 0-second hold
    ['2024-12-03 10:00', '2024-12-03 10:00', 300, 300, 0],
  ];
  rows.forEach(([a, b, pnl, mfe, mae], i) => {
    lines.push(`${i + 1},Entry long,${a},S,100,1,${pnl},${mfe},${mae}`);
    lines.push(`${i + 1},Exit long,${b},S,100,1,${pnl},${mfe},${mae}`);
  });
  const file = join(dir, 'list.csv');
  writeFileSync(file, `${lines.join('\n')}\n`);
  const base = ['--firm', 'tradeify', '--trades', file, '--runs', '20', '--horizon', '5', '--contracts', '1'];

  const plain = run([...base, '--json']).data;
  assert.equal(plain.source.flatTimeViolations, 0, 'early-close days are only known when listed');
  assert.deepEqual(plain.source.earlyCloseDays, []);
  const ms = plain.source.microscalping;
  assert.equal(ms.passes, false);
  assert.equal(ms.longShareOfTrades, 1 / 3);
  assert.equal(ms.sameTimestamp, 2);
  assert.equal(plain.rules.fundedRules.minActivity, rules.fundedRules.minActivity);
  const text = run(base).text;
  assert.match(text, /flat time: no trade open after 16:45 ET .*early-close days \(12:59 ET\) not checked: list them with --early-close/);
  assert.match(text, /WARNING: microscalping: 33\.3% of trades and 25\.0% of gross profit come from holds over 10 s/);
  assert.match(text, /2 trade\(s\) open and close on the same CSV timestamp/);
  assert.match(text, /not modelled: minimum activity/);

  const early = run([...base, '--early-close', '2024-12-24, 2024-11-29', '--json']).data;
  assert.deepEqual(early.source.earlyCloseDays, ['2024-11-29', '2024-12-24']);
  assert.equal(early.source.flatTimeViolations, 1);
  assert.deepEqual(early.source.flatTimeTrades, [1]);
  assert.match(run([...base, '--early-close', '2024-11-29']).text, /WARNING: 1 trade\(s\) \(#1\) .*12:59 ET on the 1 --early-close day/);
  assert.throws(() => run([...base, '--early-close', '2024-02-30']), /bad date "2024-02-30"/);
  assert.throws(() => run([...base, '--early-close', '11/29/2024']), /bad date/);
  assert.throws(() => run([...base, '--early-close', ',']), /one or more dates/);
});
