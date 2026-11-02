import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadRules } from '../ledger.mjs';
import { makeEmpiricalSource, simulateEval, simulatePa, replayEval, defaultSizes, sweep, RISK_MULTIPLIERS } from '../sim.mjs';
import { run } from '../cli.mjs';

const rules = loadRules();

// Weekday sessions 2024-01-01 (Mon) .. 2024-01-12 (Fri), one trade per session.
const days = ['01', '02', '03', '04', '05', '08', '09', '10', '11', '12'].map((d) => `2024-01-${d}`);
const mk = (i, dayKey, contracts, pnlPer, mfePer, maePer) => ({
  tradeNo: i + 1,
  dayKey,
  exitTime: new Date(`${dayKey}T15:00:00Z`),
  contracts,
  pnl: pnlPer * contracts,
  pnlPer,
  mfePer,
  maePer,
});

test('risk scaling with every trade at 2 contracts equals fixed contracts at 2k', () => {
  const trades = days.map((d, i) => mk(i, d, 2, i % 3 === 0 ? -50 : 80, i % 3 === 0 ? 20 : 90, i % 3 === 0 ? -50 : -30));
  const risk = makeEmpiricalSource(trades, { scaling: 'risk' });
  const fixed = makeEmpiricalSource(trades);
  for (const k of [1, 2, 3]) {
    const a = simulateEval(rules, risk, { contracts: k, attempts: 3000, seed: 5 });
    const b = simulateEval(rules, fixed, { contracts: 2 * k, attempts: 3000, seed: 5 });
    assert.equal(a.passed, b.passed, `k=${k}`);
    assert.equal(a.breached, b.breached, `k=${k}`);
    assert.equal(a.scaling, 'risk');
    const pa = simulatePa(rules, risk, { contracts: k, paRuns: 1500, seed: 6, horizonDays: 30 });
    const pb = simulatePa(rules, fixed, { contracts: 2 * k, paRuns: 1500, seed: 6, horizonDays: 30 });
    assert.equal(pa.meanPaid, pb.meanPaid, `PA k=${k}`);
    const ra = replayEval(rules, trades, { contracts: k, scaling: 'risk' });
    const rb = replayEval(rules, trades, { contracts: 2 * k });
    assert.deepEqual([ra.passed, ra.breached, ra.expired, ra.open], [rb.passed, rb.breached, rb.expired, rb.open], `replay k=${k}`);
  }
});

test('risk scaling keeps different trade sizes apart and caps each trade at the plan limit', () => {
  // Day 1: a 1-contract winner; day 2: a 4-contract loser. At k=5 (minis) the winner trades 5 (under the
  // cap of 6) and the loser wants 20, so it is capped at 6; at k=10 both are capped.
  const trades = [mk(0, '2024-01-01', 1, 100, 100, 0), mk(1, '2024-01-02', 4, -100, 0, -100)];
  const src = makeEmpiricalSource(trades, { scaling: 'risk' });
  assert.equal(src.minQty, 1);
  assert.equal(src.maxQty, 4);
  const r = simulateEval(rules, src, { contracts: 5, attempts: 4000, seed: 2, tradingDays: 1 });
  assert.ok(r.capped && r.cappedTradeShare > 0.4 && r.cappedTradeShare < 0.6, `capped share ${r.cappedTradeShare}`);
  assert.equal(simulateEval(rules, src, { contracts: 10, attempts: 500, seed: 2, tradingDays: 1 }).cappedTradeShare, 1);
  assert.equal(simulateEval(rules, src, { contracts: 1, attempts: 500, seed: 2, tradingDays: 1 }).capped, false);
  // Replay at k=5: winner +$500, loser capped at 6 contracts -$600 (uncapped it would be -$2,000, a breach).
  const rep = replayEval(rules, trades, { contracts: 5, scaling: 'risk' });
  assert.equal(rep.breached, 0);
  assert.equal(rep.passed, 0);
  // Without the cap the same trades at 20 contracts would breach: check contracts mode at 6 books -$600 too.
  const fixed = replayEval(rules, trades, { contracts: 6 });
  assert.equal(fixed.breached, 0);
});

test('risk scaling applies the PA tier cap per trade', () => {
  // A 1-contract trade that loses $1,200 per contract: at k=4 it wants 4 minis, Level 1 allows 2,
  // so the loss is $2,400 at the cap, which breaches the $2,000 PA drawdown on the first day.
  const trades = [mk(0, '2024-01-01', 1, -1200, 0, -1200)];
  const src = makeEmpiricalSource(trades, { scaling: 'risk' });
  const pa = simulatePa(rules, src, { contracts: 4, paRuns: 50, seed: 1, horizonDays: 1 });
  assert.equal(pa.pBreach, 1);
  // At k=1 the loss is $1,200 (DLL $1,000 halts the day at the adverse extreme in the default model).
  const pa1 = simulatePa(rules, src, { contracts: 1, paRuns: 50, seed: 1, horizonDays: 1 });
  assert.equal(pa1.pBreach, 0);
});

test('default sizes: contracts 1..cap; risk multipliers up to the first that caps the smallest trade', () => {
  const fixed = makeEmpiricalSource([mk(0, '2024-01-01', 1, 10, 10, 0)]);
  assert.deepEqual(defaultSizes(fixed, 6), [1, 2, 3, 4, 5, 6]);
  const r1 = makeEmpiricalSource([mk(0, '2024-01-01', 1, 10, 10, 0)], { scaling: 'risk' });
  assert.deepEqual(defaultSizes(r1, 60), RISK_MULTIPLIERS.filter((k) => k <= 60));
  const r3 = makeEmpiricalSource([mk(0, '2024-01-01', 3, 10, 10, 0), mk(1, '2024-01-02', 5, 10, 10, 0)], { scaling: 'risk' });
  assert.deepEqual(defaultSizes(r3, 6), [1, 2]);
  assert.deepEqual(sweep(rules, r3, { attempts: 10, mode: 'eval' }).sizes, [1, 2]);
  assert.throws(() => makeEmpiricalSource([mk(0, '2024-01-01', 1, 1, 1, 0)], { scaling: 'dollars' }), /scaling/);
});

test('CLI --scale auto picks risk when trade sizes vary and contracts when they do not', () => {
  const dir = mkdtempSync(join(tmpdir(), 'apex-risk-'));
  const write = (name, sizes) => {
    const lines = ['Trade #,Type,Date and time,Signal,Price USD,Position size (qty),Net P&L USD,Favorable excursion USD,Adverse excursion USD'];
    sizes.forEach((q, i) => {
      const d = days[i];
      for (const typ of ['Entry long', 'Exit long']) lines.push(`${i + 1},${typ},${d} 10:00,S,100,${q},${50 * q},${60 * q},${-20 * q}`);
    });
    const p = join(dir, name);
    writeFileSync(p, `${lines.join('\n')}\n`);
    return p;
  };
  const vary = run(['--trades', write('vary.csv', [1, 2, 3]), '--contracts', '1', '--mode', 'eval', '--attempts', '50', '--json']).data;
  assert.equal(vary.settings.scaling, 'risk');
  assert.equal(vary.source.scaleAuto, true);
  const same = run(['--trades', write('same.csv', [2, 2, 2]), '--contracts', '1', '--mode', 'eval', '--attempts', '50', '--json']).data;
  assert.equal(same.settings.scaling, 'contracts');
  const forced = run(['--trades', write('f.csv', [1, 2, 3]), '--scale', 'contracts', '--contracts', '1', '--mode', 'eval', '--attempts', '50', '--json']).data;
  assert.equal(forced.settings.scaling, 'contracts');
  assert.throws(() => run(['--win', '0.5', '--rr', '1', '--risk', '100', '--scale', 'risk']), /needs --trades/);
  assert.throws(() => run(['--trades', write('g.csv', [1]), '--scale', 'nope']), /--scale must be/);
});
