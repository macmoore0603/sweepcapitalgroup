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

import { mergeLegs } from '../tv-csv.mjs';

test('scale-out legs (same side and entry time) merge into one position before sizing and caps', () => {
  const entry = new Date('2024-01-02T14:35:00Z');
  const leg = (n, qty, pnlPer, exitMin) => ({
    tradeNo: n,
    side: 'long',
    entryTime: entry,
    exitTime: new Date(entry.getTime() + exitMin * 60000),
    dayKey: '2024-01-02',
    contracts: qty,
    pnl: pnlPer * qty,
    runUp: Math.max(0, pnlPer) * qty,
    drawdown: -250 * qty,
    pnlPer,
    mfePer: Math.max(0, pnlPer),
    maePer: -250,
  });
  const { trades, merged } = mergeLegs([leg(1, 3, -250, 10), leg(2, 3, -250, 12), { ...leg(3, 2, 100, 30), entryTime: new Date('2024-01-02T15:00:00Z') }]);
  assert.equal(merged, 1);
  assert.equal(trades.length, 2);
  const p = trades[0];
  assert.equal(p.contracts, 6);
  assert.equal(p.pnl, -1500);
  assert.equal(p.legs, 2);
  assert.equal(p.maePer, -250);
  assert.equal(p.exitTime.getTime(), entry.getTime() + 12 * 60000, 'exits with the last leg');
  // The 6-lot position already sits at the 6-mini eval cap: risk x2 must stay capped at 6, not 12.
  const rep = replayEval(rules, [p], { contracts: 2, scaling: 'risk' });
  assert.equal(rep.breached, 0, 'capped at 6 minis: -$1,500 does not breach the $2,000 drawdown');
  const legsApart = replayEval(rules, [leg(1, 3, -250, 10), leg(2, 3, -250, 12)], { contracts: 2, scaling: 'risk' });
  assert.equal(legsApart.breached, 1, 'without merging, each leg is capped on its own and the position doubles');
});

test('risk sweep includes the first multiplier that caps every trade; CLI messages and calendar options', () => {
  const r9 = makeEmpiricalSource([mk(0, '2024-01-01', 9, 10, 10, 0)], { scaling: 'risk' });
  assert.deepEqual(defaultSizes(r9, 60), [1, 2, 3, 4, 5, 6, 8], '9 x 6 = 54 < 60, so 8 (72) is the first fully capped multiplier');
  const dir = mkdtempSync(join(tmpdir(), 'apex-cal-'));
  const lines = ['Trade #,Type,Date and time,Signal,Price USD,Position size (qty),Net P&L USD,Favorable excursion USD,Adverse excursion USD'];
  [['2024-01-03', 1], ['2024-01-04', 2]].forEach(([d, q], i) => {
    for (const typ of ['Entry long', 'Exit long']) lines.push(`${i + 1},${typ},${d} 10:00,S,100,${q},${50 * q},${60 * q},${-20 * q}`);
  });
  const f = join(dir, 'c.csv');
  writeFileSync(f, `${lines.join('\n')}\n`);
  const base = run(['--trades', f, '--contracts', '1', '--mode', 'eval', '--attempts', '20', '--json']).data;
  assert.equal(base.source.sessions, 2);
  const wide = run(['--trades', f, '--from', '2024-01-01', '--to', '2024-01-12', '--contracts', '1', '--mode', 'eval', '--attempts', '20', '--json']).data;
  assert.equal(wide.source.sessions, 10, 'Mon 1 Jan .. Fri 12 Jan: 10 weekday sessions');
  assert.throws(() => run(['--trades', f, '--from', '2024-13-01']), /--from must be a date/);
  assert.throws(() => run(['--trades', f, '--from', '2024-01-12', '--to', '2024-01-01']), /must not be after/);
  assert.throws(() => run(['--win', '0.5', '--rr', '1', '--risk', '100', '--from', '2024-01-01']), /only applies with --trades/);
  assert.throws(() => run(['--win', '0.5', '--rr', '1', '--risk', '100', '--scale', 'nope']), /--scale must be auto, contracts or risk/);
  assert.throws(() => run(['--trades', f, '--contracts', '61', '--mode', 'eval']), /risk multiplier/);
  // A micro-sized export read as minis: trades above the 6-mini cap are flagged.
  const big = join(dir, 'big.csv');
  const bl = [lines[0]];
  [['2024-01-03', 8], ['2024-01-04', 12]].forEach(([d, q], i) => {
    for (const typ of ['Entry long', 'Exit long']) bl.push(`${i + 1},${typ},${d} 10:00,S,100,${q},${5 * q},${6 * q},${-2 * q}`);
  });
  writeFileSync(big, `${bl.join('\n')}\n`);
  const warned = run(['--trades', big, '--contracts', '1', '--mode', 'eval', '--attempts', '20']).text;
  assert.match(warned, /WARNING: 2 of 2 trades exceed the evaluation cap \(6 minis\)/);
  assert.match(warned, /Capped/);
});
