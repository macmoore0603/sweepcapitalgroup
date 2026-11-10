import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  loadRules,
  validateRules,
  makePaLedger,
  tierFor,
  stepTrade,
  closeTrade,
  startDay,
  endDay,
  payoutCheck,
  payoutsDone,
  contractCap,
  balance,
  ACTIVE,
  BREACHED,
} from '../ledger.mjs';

const rules = loadRules();
const S = rules.startBalance;
const PA = rules.performanceAccount;
const PO = PA.payout;
const tiers = PA.tiers;

/** One session made of closed trades (no excursions); returns the payout paid at the session end. */
function session(P, key, ...pnls) {
  startDay(P, key);
  for (const x of pnls) closeTrade(P, x);
  return endDay(P);
}

test('tier boundaries and the Level 1 floor', () => {
  assert.deepEqual(
    tiers.map((t) => t.minProfit),
    [0, 1500, 3000, 6000],
  );
  assert.equal(tierFor(tiers, -1500).level, 1, 'never below Level 1');
  assert.equal(tierFor(tiers, -0.01).level, 1);
  assert.equal(tierFor(tiers, 0).level, 1);
  for (let i = 1; i < tiers.length; i++) {
    assert.equal(tierFor(tiers, tiers[i].minProfit - 0.01).level, tiers[i - 1].level, `just below tier ${i + 1}`);
    assert.equal(tierFor(tiers, tiers[i].minProfit).level, tiers[i].level, `at tier ${i + 1}`);
  }
  assert.equal(tierFor(tiers, 1e6).level, tiers[tiers.length - 1].level);
  assert.equal(tierFor(rules, 3000).level, 3, 'accepts the rules object');
});

test('tier comes from the prior session closing balance, not intraday balance', () => {
  const P = makePaLedger(rules);
  assert.equal(P.tier.level, 1);
  assert.equal(contractCap(P, 'mini'), tiers[0].maxContractsMini);
  session(P, 1, tiers[1].minProfit + 100); // close at 51600
  startDay(P, 2);
  assert.equal(P.tier.level, 2);
  assert.equal(contractCap(P, 'mini'), tiers[1].maxContractsMini);
  assert.equal(contractCap(P, 'micro'), tiers[1].maxContractsMini * rules.microsPerMini);
  closeTrade(P, 2000); // 53600 intraday: still tier 2 this session
  assert.equal(P.tier.level, 2);
  endDay(P);
  startDay(P, 3);
  assert.equal(P.tier.level, 3);
  assert.equal(P.tier.dailyLossLimit, tiers[2].dailyLossLimit);
  closeTrade(P, -1000); // close 52600 -> profit 2600 -> back to tier 2
  endDay(P);
  startDay(P, 4);
  assert.equal(P.tier.level, 2);

  const Q = makePaLedger(rules);
  session(Q, 1, -500); // below start
  startDay(Q, 2);
  assert.equal(Q.tier.level, 1);
});

test('daily loss limit flattens, pauses the rest of the session, resumes next session', () => {
  for (const dllFill of ['extreme', 'limit']) {
    const P = makePaLedger(rules, { dllFill });
    startDay(P, 1);
    const dll = P.tier.dailyLossLimit;
    const adverse = -(dll + 300);
    assert.equal(stepTrade(P, { favorable: 100, adverse, close: adverse }), ACTIVE, dllFill);
    // extreme: flattened at the trade's adverse extreme; limit: exactly at the daily loss limit.
    assert.equal(P.realized, dllFill === 'extreme' ? adverse : -dll, dllFill);
    assert.equal(P.dayHalted, true);
    assert.equal(P.status, ACTIVE, 'account stays open');
    const n = P.trades;
    const r = P.realized;
    stepTrade(P, { favorable: 500, adverse: 0, close: 500 }); // ignored for the rest of the session
    assert.equal(P.realized, r);
    assert.equal(P.trades, n);
    endDay(P);
    startDay(P, 2);
    assert.equal(P.dayHalted, false);
    stepTrade(P, { favorable: 300, adverse: -50, close: 300 });
    assert.equal(P.realized, r + 300);
  }
});

test('daily loss limit counts realized losses earlier in the session plus open P&L', () => {
  for (const dllFill of ['extreme', 'limit']) {
    const P = makePaLedger(rules, { dllFill });
    startDay(P, 1);
    const dll = P.tier.dailyLossLimit;
    stepTrade(P, { favorable: 0, adverse: -600, close: -600 });
    assert.equal(P.dayHalted, false);
    stepTrade(P, { favorable: 0, adverse: -600, close: -605, cost: 5 }); // open -600 on top of -600 realized
    assert.equal(P.dayHalted, true, dllFill);
    assert.equal(P.realized, dllFill === 'extreme' ? -1205 : -dll - 5, dllFill);
  }
  const Q = makePaLedger(rules);
  startDay(Q, 1);
  closeTrade(Q, -Q.tier.dailyLossLimit); // realized loss exactly at the limit also pauses the session
  assert.equal(Q.dayHalted, true);
});

test('DLL fill: extreme checks the breach at the true low; limit liquidation can prevent it', () => {
  const trade = { favorable: 0, adverse: -(PA.maxDrawdown + 100), close: -(PA.maxDrawdown + 100) };
  const X = makePaLedger(rules); // default 'extreme'
  startDay(X, 1);
  assert.equal(stepTrade(X, trade), BREACHED);
  const Lm = makePaLedger(rules, { dllFill: 'limit' });
  startDay(Lm, 1);
  assert.equal(stepTrade(Lm, trade), ACTIVE);
  assert.equal(Lm.realized, -Lm.tier.dailyLossLimit);
  assert.equal(Lm.dayHalted, true);
});

test('trailing threshold above the DLL level is touched first => breach (either DLL fill)', () => {
  const P = makePaLedger(rules, { dllFill: 'limit' });
  startDay(P, 1);
  stepTrade(P, { favorable: 1900, adverse: 0, close: 100 }); // peak 51900 -> threshold 49900, close 50100
  assert.equal(P.threshold, S + 1900 - PA.maxDrawdown);
  endDay(P);
  startDay(P, 2); // tier 1, DLL level 50100 - 1000 = 49100 is below the 49900 threshold
  assert.ok(balance(P) - P.tier.dailyLossLimit <= P.threshold);
  assert.equal(stepTrade(P, { favorable: 0, adverse: -1200, close: -1200 }), BREACHED);
});

test('money is kept in cents: tier, qualifying-day and daily-loss boundaries are exact', () => {
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);
  const toTier2 = [202.59, 482.69, 488.08, 285.55, 41.09]; // 1,500.00 in cents
  assert.ok(sum(toTier2) < tiers[1].minProfit, 'raw float sum falls short of 1500');
  const P = makePaLedger(rules);
  session(P, 1, ...toTier2);
  startDay(P, 2);
  assert.equal(P.realized, tiers[1].minProfit);
  assert.equal(P.tier.level, 2);

  const Q = makePaLedger(rules);
  session(Q, 1, 200.02);
  session(Q, 2, 0.07, 199.93); // a $200.00 day
  assert.equal(Q.lastDayPnl, PO.minDailyProfit);
  assert.equal(Q.qualDays, 2);

  const toDll = [-134.06, -324.14, -518.37, -23.43]; // -1,000.00 in cents
  assert.ok(sum(toDll) > -tiers[0].dailyLossLimit, 'raw float sum stays above -1000');
  const D = makePaLedger(rules);
  startDay(D, 1);
  for (const x of toDll) closeTrade(D, x);
  assert.equal(D.dayHalted, true, 'a session at exactly -$1,000.00 pauses');
});

test('payout needs the minimum number of qualifying days', () => {
  const P = makePaLedger(rules);
  for (let d = 1; d <= PO.minQualifyingDays - 1; d++) assert.equal(session(P, d, 700), 0);
  const c = payoutCheck(P);
  assert.equal(c.daysOk, false);
  assert.ok(c.consistencyOk && c.balanceOk && c.minPayoutOk && c.countOk, 'only the day count is missing');
  const paid = session(P, PO.minQualifyingDays, 200); // 5th qualifying day; balance 53000
  assert.equal(paid, Math.min(PO.maxPerRequest[0], S + 3000 - PO.safetyNet)); // 900
  assert.equal(P.payouts, 1);
  assert.equal(balance(P), PO.safetyNet);
  assert.equal(P.qualDays, 0, 'window resets after a payout');
  assert.equal(P.windowProfit, 0);
});

test('a qualifying day needs net P&L >= $200', () => {
  const P = makePaLedger(rules);
  for (let d = 1; d <= 4; d++) session(P, d, 700);
  assert.equal(session(P, 5, PO.minDailyProfit - 1), 0, '$199 day does not qualify');
  assert.equal(P.qualDays, 4);
  assert.equal(session(P, 6, PO.minDailyProfit), S + 2800 + 199 + 200 - PO.safetyNet); // $200 day qualifies -> 1099
});

test('consistency: largest profitable day must be < 50% of profit since the last payout', () => {
  const P = makePaLedger(rules);
  assert.equal(session(P, 1, 1500), 0);
  for (let d = 2; d <= 5; d++) assert.equal(session(P, d, 300), 0);
  let c = payoutCheck(P); // total 2700, largest 1500 >= 1350
  assert.equal(c.consistencyOk, false);
  assert.ok(c.daysOk && c.balanceOk && c.minPayoutOk);
  assert.equal(session(P, 6, 300), 0, 'exactly 50% (1500 of 3000) is not enough');
  c = payoutCheck(P);
  assert.equal(c.windowMaxDay, 1500);
  assert.equal(c.windowProfit, 3000);
  assert.equal(session(P, 7, 300), Math.min(PO.maxPerRequest[0], S + 3300 - PO.safetyNet)); // 1500 < 1650 -> 1200
});

test('payout needs balance >= 52600 and pays down to no less than 52100', () => {
  const P = makePaLedger(rules);
  for (let d = 1; d <= 5; d++) session(P, d, 500); // 52500
  const c = payoutCheck(P);
  assert.equal(c.balanceOk, false);
  assert.ok(c.daysOk && c.consistencyOk);
  assert.equal(P.payouts, 0);
  assert.equal(session(P, 6, 100), PO.minBalanceToRequest - PO.safetyNet); // at 52600 -> $500
  assert.equal(balance(P), PO.safetyNet);
});

test('payout needs amount >= $500 (checked on its own with a lower request balance)', () => {
  const custom = structuredClone(rules);
  custom.performanceAccount.payout.minBalanceToRequest = PO.safetyNet + 100; // 52200, so only $500 min binds
  validateRules(custom);
  const P = makePaLedger(custom);
  for (let d = 1; d <= 5; d++) session(P, d, 500); // 52500 -> amount 400
  const c = payoutCheck(P);
  assert.equal(c.balanceOk, true);
  assert.equal(c.minPayoutOk, false);
  assert.equal(P.payouts, 0);
  assert.equal(session(P, 6, 100), PO.minPayout);
});

test('per-request caps apply in order and payouts stop after the maximum count', () => {
  const P = makePaLedger(rules);
  const got = [];
  let d = 0;
  for (let cycle = 0; cycle < PO.maxPayouts + 2; cycle++) {
    for (let k = 1; k <= PO.minQualifyingDays; k++) {
      const p = session(P, ++d, 2000);
      if (k < PO.minQualifyingDays) assert.equal(p, 0, 'needs a fresh set of qualifying days after each payout');
      if (p > 0) got.push(p);
    }
  }
  assert.deepEqual(got, PO.maxPerRequest.slice(0, PO.maxPayouts));
  assert.deepEqual(got, [1500, 2000, 2500, 2500, 3000, 3000]);
  assert.equal(P.payouts, PO.maxPayouts);
  assert.equal(P.paid, got.reduce((a, b) => a + b, 0));
  assert.equal(payoutsDone(P), true);
  assert.equal(payoutCheck(P).countOk, false);
  assert.equal(P.payoutHistory.length, PO.maxPayouts);
});
