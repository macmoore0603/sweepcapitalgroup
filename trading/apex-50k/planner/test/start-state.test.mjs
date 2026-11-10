// Start from the funded account held now (--balance/--floor/... with --firm tradeify): validation, the
// ledger at a start state, payouts counted from the start, and the CLI end to end.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  loadTradeifyRules,
  validateTradeifyRules,
  resolveStartState,
  makeFundedLedger,
  closeTrade,
  stepTrade,
  startDay,
  endDay,
  payoutCheck,
  payoutBlockers,
  payoutsMade,
  requestIfEligible,
  contractCap,
  balance,
  simulateFunded,
  replayFunded,
  ACTIVE,
  BREACHED,
} from '../tradeify.mjs';
import { makeEmpiricalSource, makeParametricSource } from '../sim.mjs';
import { run, parseStartArgs } from '../cli.mjs';

const rules = loadTradeifyRules();
const S = rules.startBalance;
const D = rules.drawdown;

/** One session of closed trades; returns the payout requested at the close. */
function day(L, ...pnls) {
  startDay(L, L.sessions + 1);
  for (const x of pnls) closeTrade(L, x);
  return endDay(L);
}
const days = (L, list) => list.map((x) => day(L, x));
const growth = (state, opts = {}) => makeFundedLedger(rules, 'growth', { ...opts, startState: state });
/** Eligible-now Growth state: 5 qualifying days, 33.3% consistency, balance 53000, floor locked. */
const READY = { balance: 53000, floor: 50100, highEod: 53000, qualDays: 5, cycleMaxDay: 1000 };

test('start state: required fields, defaults and validation errors', () => {
  const st = resolveStartState(rules, 'growth', { balance: 51500, floor: 49800, highEod: 51800, qualDays: 3, cycleMaxDay: 600 });
  assert.equal(st.cycleStart, S, 'cycle start defaults to the start balance');
  assert.equal(st.payoutsTaken, 0);
  assert.equal(st.cycleProfit, 1500);
  assert.equal(st.roomToFloor, 1700);
  assert.equal(st.locked, false);
  assert.equal(st.expectedFloor, 49800);
  assert.deepEqual(st.warnings, []);
  const h = resolveStartState(rules, 'growth', { balance: 50700, floor: 48500, qualDays: 1, cycleMaxDay: 400 });
  assert.equal(h.highEod, 50700, 'high-eod defaults to the largest of the balance, the start balance and floor + 2000');
  assert.equal(resolveStartState(rules, 'growth', { balance: 49500, floor: 48000 }).highEod, S);
  assert.equal(resolveStartState(rules, 'growth', { balance: 49500, floor: 48000 }).cycleMaxDay, 0, 'not required when B <= S');

  const bad = (input, re, plan = 'growth') => assert.throws(() => resolveStartState(rules, plan, input), re, JSON.stringify(input));
  bad({ floor: 48000 }, /--balance is required/);
  bad({ balance: 50000 }, /--floor is required/);
  bad({ balance: 'x', floor: 48000 }, /--balance must be a number/);
  bad({ balance: 48000, floor: 48000 }, /not above --floor .*already breached/);
  bad({ balance: 47000, floor: 48000 }, /already breached/);
  bad({ balance: 51000, floor: 49000, highEod: 50500, cycleMaxDay: 800 }, /--high-eod \$50,500\.00 is below --balance/);
  bad({ balance: 49000, floor: 47500, highEod: 49500 }, /below the \$50,000\.00 start balance/);
  bad({ balance: 51000, floor: 49000, cycleStart: 51000 }, /--cycle-start must be the \$50,000\.00 start balance while no payout/);
  bad({ balance: 51000, floor: 49000 }, /--cycle-max-day is required when --balance is above --cycle-start .* 35% consistency/);
  bad({ balance: 49900, floor: 48000, qualDays: 1 }, /--cycle-max-day is required when --qual-days is 1/);
  bad({ balance: 51000, floor: 49000, cycleMaxDay: -1 }, /--cycle-max-day must be >= 0/);
  bad({ balance: 51000, floor: 49000, qualDays: 2, cycleMaxDay: 150 }, /--qual-days 2 needs --cycle-max-day above \$150\.00/);
  bad({ balance: 51000, floor: 49000, qualDays: 1.5, cycleMaxDay: 800 }, /--qual-days must be a whole number >= 0/);
  bad({ balance: 51000, floor: 49000, qualDays: -1, cycleMaxDay: 800 }, /--qual-days must be a whole number/);
  bad({ balance: 51000, floor: 50100, cycleMaxDay: 800, payoutsTaken: 0.5 }, /--payouts-taken must be a whole number/);
  bad({ balance: 51000, floor: 50100, cycleMaxDay: 800, payoutsTaken: 1 }, /--cycle-start \$50,000\.00 is not above the floor .* right after the last payout/);
  bad({ balance: 52500, floor: 50100, highEod: 54000, cycleStart: 54500, cycleMaxDay: 300, payoutsTaken: 1 }, /--cycle-start .* is above --high-eod/);
  bad({ balance: 51000, floor: 49000, qualDays: 2, cycleMaxDay: 800 }, /--qual-days does not apply to Lightning/, 'lightning');
  bad({ balance: 51000, floor: 49000, qualDays: 2 }, /--qual-days does not apply to Select Daily/, 'select-daily');
  // Select Flex: no consistency rule, so the largest day is optional; winning days are >= $150.
  assert.doesNotThrow(() => resolveStartState(rules, 'select-flex', { balance: 51000, floor: 49000, qualDays: 2 }));
  bad({ balance: 51000, floor: 49000, qualDays: 2, cycleMaxDay: 149.99 }, /of at least \$150\.00/, 'select-flex');
  assert.doesNotThrow(() => resolveStartState(rules, 'select-flex', { balance: 51000, floor: 49000, qualDays: 2, cycleMaxDay: 150 }));
  assert.throws(() => makeFundedLedger(rules, 'growth', { startState: { balance: 48000, floor: 48000 } }), /already breached/, 'the ledger validates too');
});

test('start state: an impossible floor is rejected (unlocked: from 48000 up to below 50100; locked: 50100)', () => {
  const bad = (input, re) => assert.throws(() => resolveStartState(rules, 'growth', input), re, JSON.stringify(input));
  const M = { qualDays: 2, cycleMaxDay: 600 };
  // "$49,000" unquoted in a shell arrives as "9,000".
  bad({ balance: 51000, floor: 9000, ...M }, /--floor \$9,000\.00 is below \$48,000\.00, the lowest floor .*; in a shell an unquoted \$ amount loses its first digit \(\$49,000 arrives as 9,000\)/);
  assert.throws(() => resolveStartState(rules, 'growth', { balance: 49000, floor: 47999.99 }), (e) => /is below \$48,000\.00, the lowest floor/.test(e.message) && !/in a shell/.test(e.message));
  bad({ balance: 52000, floor: 50300, highEod: 52050, ...M }, /--floor \$50,300\.00 is above \$50,100\.00: the floor never goes higher/);
  bad({ balance: 52000, floor: 50300, ...M }, /is above \$50,100\.00/);
  bad({ balance: 52000, floor: 50100, highEod: 52050, ...M }, /--floor \$50,100\.00 with --high-eod \$52,050\.00: the floor locks at \$50,100\.00 only once a close reaches \$52,100\.00 or a payout is requested, so until then it is below \$50,100\.00 \(here \$50,050\.00\)/);
  // Without --high-eod a 50100 floor means a close reached 52100: locked, not a warning.
  const lockedByFloor = resolveStartState(rules, 'growth', { balance: 51000, floor: 50100, ...M });
  assert.equal(lockedByFloor.highEod, 52100);
  assert.equal(lockedByFloor.locked, true);
  assert.equal(lockedByFloor.lockedBy, 'eod');
  assert.deepEqual(lockedByFloor.warnings, []);
  assert.doesNotThrow(() => resolveStartState(rules, 'growth', { balance: 49500, floor: 48000 }), 'the lowest floor itself');
  // The CLI: an unquoted $ amount is an error, not a warning.
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1'];
  assert.throws(() => run([...base, '--balance', '51000', '--floor', '9,000', '--cycle-max-day', '600', '--qual-days', '2']), /--floor \$9,000\.00 is below \$48,000\.00/);
});

test('start state: day counts and the largest day must agree', () => {
  const bad = (input, re, plan = 'growth') => assert.throws(() => resolveStartState(rules, plan, input), re, `${plan} ${JSON.stringify(input)}`);
  // A largest day above $150 on Growth was itself a qualifying day.
  bad({ balance: 53500, floor: 50100, highEod: 53500, cycleMaxDay: 900 }, /--qual-days is 0 but --cycle-max-day \$900\.00 is above \$150\.00: that day was itself a qualifying day, so give --qual-days \(at least 1\)/);
  assert.doesNotThrow(() => resolveStartState(rules, 'growth', { balance: 50100, floor: 48100, qualDays: 0, cycleMaxDay: 150 }), 'a $150.00 day does not qualify');
  bad({ balance: 51000, floor: 49000, cycleMaxDay: 200 }, /--qual-days is 0 but --cycle-max-day \$200\.00 is at least \$150\.00: that day was itself a winning day/, 'select-flex');
  assert.doesNotThrow(() => resolveStartState(rules, 'select-flex', { balance: 51000, floor: 49000, cycleMaxDay: 149.99 }));
  // A positive profit since the last payout needs a profitable day.
  bad({ balance: 51000, floor: 49000, cycleMaxDay: 0 }, /--cycle-max-day is \$0\.00 but the profit since the last payout is \$1,000\.00: a positive profit needs at least one profitable day/);
  bad({ balance: 51000, floor: 49000, cycleMaxDay: 0 }, /needs at least one profitable day/, 'lightning');
  assert.doesNotThrow(() => resolveStartState(rules, 'growth', { balance: 49900, floor: 48000, cycleMaxDay: 0 }));
  // Before the first payout a close above $50,000 means this cycle had a profitable day: the largest day is needed.
  bad({ balance: 49900, floor: 49500, highEod: 51500 }, /--cycle-max-day is required when --high-eod \$51,500\.00 is above the \$50,000\.00 start balance \(this cycle has had a profitable day\): the 20% consistency/, 'lightning');
  bad({ balance: 49900, floor: 49500, highEod: 51500 }, /--cycle-max-day is required when --high-eod \$51,500\.00 is above .* 35% consistency/);
  bad({ balance: 49900, floor: 49500 }, /--cycle-max-day is required when --high-eod \$51,500\.00 \(not given: .*--floor \+ \$2,000\.00\) is above/);
  const lt = resolveStartState(rules, 'lightning', { balance: 49900, floor: 49500, highEod: 51500, cycleMaxDay: 1500 });
  assert.equal(lt.cycleMaxDay, 1500);
  assert.equal(payoutBlockers(makeFundedLedger(rules, 'lightning', { startState: lt })).find((b) => b.check === 'consistency').message.includes('$7,500.00'), true, '1500 / 20%');
  assert.doesNotThrow(() => resolveStartState(rules, 'select-flex', { balance: 49900, floor: 49500, highEod: 51500 }), 'no consistency rule');
  assert.doesNotThrow(() => resolveStartState(rules, 'growth', { balance: 49900, floor: 48000, highEod: S }), 'never above the start balance');
});

test('start state: --high-eod after a payout defaults to the lowest close a payout needs', () => {
  // Payout 1 taken (Growth: balance 51500 after it), now 51200: valid without --high-eod.
  const st = resolveStartState(rules, 'growth', { balance: 51200, floor: 50100, cycleStart: 51500, payoutsTaken: 1 });
  assert.equal(st.highEod, 53000, 'a Growth payout needs a 53000 balance');
  assert.equal(st.cycleProfit, -300);
  assert.equal(st.dll, 2000, 'a close reached 53000: DLL raised, as in the ledger');
  assert.deepEqual(st.notes.filter((n) => /--high-eod not given/.test(n)), [], 'no note where H does not change the result');
  assert.equal(resolveStartState(rules, 'lightning', { balance: 51200, floor: 50100, cycleStart: 51200, payoutsTaken: 1 }).highEod, 53000, 'Lightning: profit goal 1');
  const daily = resolveStartState(rules, 'select-daily', { balance: 51000, floor: 50100, cycleStart: 51000, payoutsTaken: 1 });
  assert.equal(daily.highEod, 52350, 'buffer 52100 + the $250 minimum');
  assert.equal(daily.capMini, 4);
  const flex = resolveStartState(rules, 'select-flex', { balance: 50400, floor: 50100, cycleStart: 50300, payoutsTaken: 1 });
  assert.equal(flex.highEod, 50500, 'half the profit must reach the $250 minimum');
  assert.equal(flex.lockedBy, 'payout');
  assert.match(flex.notes.find((n) => /--high-eod not given/.test(n)), /assumed \$50,500\.00 .*the Select contract limit comes from it/);
  assert.equal(resolveStartState(rules, 'select-flex', { balance: 50400, floor: 50100, highEod: 52200, cycleStart: 50300, payoutsTaken: 1 }).capMini, 4, 'a typed H gives the real tier');
  // A typed --high-eod is checked as before.
  assert.throws(() => resolveStartState(rules, 'growth', { balance: 51200, floor: 50100, highEod: 51300, cycleStart: 51500, payoutsTaken: 1 }), /--cycle-start \$51,500\.00 is above --high-eod \$51,300\.00/);
  // The CLI runs it.
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1'];
  const out = run([...base, '--balance', '51200', '--floor', '50100', '--cycle-start', '51500', '--payouts-taken', '1', '--json']).data;
  assert.equal(out.startState.highEod, 53000);
  assert.equal(out.startState.nextCap, 2000);
});

test('start state: a Growth cycle start must be reachable after payout K (minimum balance - its cap)', () => {
  const bad = (input, re) => assert.throws(() => resolveStartState(rules, 'growth', input), re, JSON.stringify(input));
  bad({ balance: 52000, floor: 50100, cycleStart: 50500, payoutsTaken: 1, qualDays: 2, cycleMaxDay: 600 }, /--cycle-start \$50,500\.00 is below \$51,500\.00, the lowest balance right after payout 1: a payout needs a \$53,000\.00 balance until it is approved, and payout 1 is at most \$1,500\.00/);
  bad({ balance: 52000, floor: 50100, cycleStart: 50999.99, payoutsTaken: 2, qualDays: 2, cycleMaxDay: 600 }, /below \$51,000\.00, the lowest balance right after payout 2/);
  for (const [K, S1] of [[1, 51500], [2, 51000], [3, 50500], [4, 50100.01], [9, 50100.01]]) {
    assert.doesNotThrow(() => resolveStartState(rules, 'growth', { balance: 52000, floor: 50100, cycleStart: S1, payoutsTaken: K, qualDays: 2, cycleMaxDay: 600 }), `K=${K}`);
  }
  // Legacy Growth: 52100 minimum; after the tiers up to $25,000, so only the floor bounds the cycle start.
  assert.doesNotThrow(() => resolveStartState(rules, makeLegacy(), { balance: 55000, floor: 50100, cycleStart: 50200, payoutsTaken: 7, qualDays: 2, cycleMaxDay: 600 }));
});

/** Legacy Growth, resolved (for resolveStartState with the legacy limits). */
function makeLegacy() {
  return makeFundedLedger(rules, 'growth', { legacy: true }).plan;
}

test('start state: legacy Growth after the 6th payout pays up to $25,000, limited by the floor', () => {
  const st = { balance: 60000, floor: 50100, highEod: 60000, cycleStart: 53000, qualDays: 5, cycleMaxDay: 1000, payoutsTaken: 6 };
  const L = makeFundedLedger(rules, 'growth', { legacy: true, startState: st });
  const c = payoutCheck(L);
  assert.equal(c.n, 7);
  assert.equal(c.cap, 25000);
  assert.equal(c.maxAmount, 9899.99, 'balance - floor - $0.01, far below the cap');
  assert.equal(c.eligible, true, '1000 / 7000 = 14.3%');
  assert.equal(L.dll, null, 'legacy: the DLL is removed once a close reached 53000');
  assert.equal(requestIfEligible(L), 9899.99);
  assert.equal(balance(L), 50100.01);
  // Payout 6 is the last tier ($3,000).
  const six = payoutCheck(makeFundedLedger(rules, 'growth', { legacy: true, startState: { ...st, payoutsTaken: 5 } }));
  assert.equal(six.cap, 3000);
  const text = run(['--firm', 'tradeify', '--legacy', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1',
    '--balance', '60000', '--floor', '50100', '--high-eod', '60000', '--cycle-start', '53000', '--qual-days', '5', '--cycle-max-day', '1000', '--payouts-taken', '6']).text;
  assert.match(text, /no DLL \(removed\)/);
  assert.match(text, /next is payout 7, cap \$25,000/);
  assert.match(text, /payout now: yes, \$9,899\.99 \(payout 7\)/);
});

test('start state: --payout min requests the plan minimum now', () => {
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1'];
  const ready = ['--balance', '53000', '--floor', '50100', '--high-eod', '53000', '--qual-days', '5', '--cycle-max-day', '1000'];
  const out = run([...base, ...ready, '--payout', 'min', '--json']).data;
  assert.equal(out.startState.payoutNow.amount, 500);
  assert.equal(out.startState.payoutNow.maxAmount, 1500);
  assert.deepEqual(out.results[0].payoutNow, { n: 1, amount: 500, toTrader: 450 });
  assert.match(run([...base, ...ready, '--payout', 'min']).text, /payout now: yes, \$500\.00 \(payout 1\)/);
});

test('CLI: start state with --trades: the 10-second rule, the replay row and the summary', () => {
  const dir = mkdtempSync(join(tmpdir(), 'tradeify-start-'));
  const csv = (name, rows) => {
    const lines = ['Trade #,Type,Date and time,Signal,Price USD,Position size (qty),Net P&L USD,Favorable excursion USD,Adverse excursion USD'];
    rows.forEach(([a, b, pnl, mfe, mae], i) => {
      lines.push(`${i + 1},Entry long,${a},S,100,1,${pnl},${mfe},${mae}`);
      lines.push(`${i + 1},Exit long,${b},S,100,1,${pnl},${mfe},${mae}`);
    });
    const f = join(dir, name);
    writeFileSync(f, `${lines.join('\n')}\n`);
    return f;
  };
  const ready = ['--balance', '53000', '--floor', '50100', '--high-eod', '53000', '--qual-days', '5', '--cycle-max-day', '1000'];
  const base = (file) => ['--firm', 'tradeify', '--trades', file, '--runs', '20', '--horizon', '10', '--contracts', '1', ...ready];
  // Every trade opens and closes on the same minute: 0-second holds fail the 10-second rule.
  const scalps = csv('scalps.csv', [['2024-12-02 10:00', '2024-12-02 10:00', 300, 300, 0], ['2024-12-03 10:00', '2024-12-03 10:00', -200, 0, -200]]);
  const blocked = run(base(scalps));
  assert.deepEqual(blocked.data.startState.payoutNow.blockedBy, ['microscalping']);
  assert.equal(blocked.data.startState.payoutNow.eligible, true, 'the payout rules alone allow it');
  assert.match(blocked.text, /payout now: blocked by the 10-second rule, which the --trades list fails; the payout rules alone allow \$1,500\.00 \(payout 1\)\. The run still requests it at once, as if the rule were met/);
  assert.doesNotMatch(blocked.text, /payout now: yes/);
  assert.match(blocked.text, /\(the --trades list fails it\)/);
  // Replay: the first account pays at the start state; that payout is not one the trades earned.
  const r = blocked.data.replay[0];
  assert.equal(r.startPayouts, 1);
  assert.equal(r.accounts[0].firstPayoutDay, 'start');
  assert.equal(r.payouts, 1);
  assert.match(blocked.text, /1st payout "start" = the payout requested now/);
  assert.match(blocked.text, /^\s+1\s+1\s+0\s+1\s+\$1,500\s+\$1,350\s+start\s/m);
  assert.match(blocked.text, /the historical replay reached no payout after the payout requested now at any size/);
  assert.doesNotMatch(blocked.text, /the historical replay paid out/);
  // Holds over 10 s pass it: the payout now is a plain yes; five more +300 days earn payout 2 in the replay.
  const days = ['2024-12-02', '2024-12-03', '2024-12-04', '2024-12-05', '2024-12-06'];
  const steady = csv('steady.csv', days.map((d) => [`${d} 10:00`, `${d} 10:30`, 300, 320, -20]));
  const ok = run(base(steady));
  assert.deepEqual(ok.data.startState.payoutNow.blockedBy, []);
  assert.match(ok.text, /payout now: yes, \$1,500\.00 \(payout 1\); the run requests it at once/);
  assert.match(ok.text, /\(the --trades list passes it\)/);
  assert.equal(ok.data.replay[0].payouts, 2, 'the payout now, then payout 2 after 5 days of +300 (51500 -> 53000)');
  assert.match(ok.text, /the historical replay paid out after the payout requested now at 1 mini/);
});

test('start state: the Start line shows the largest day only where a consistency rule uses it', () => {
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1'];
  const daily = run([...base, '--plan', 'select-daily', '--balance', '51000', '--floor', '49000']).text;
  assert.match(daily, /since the last payout \(cycle start \$50,000\.00\): profit \$1,000\.00; 0 payouts taken/);
  assert.doesNotMatch(daily, /largest day/);
  const growthText = run([...base, '--balance', '51000', '--floor', '49000', '--qual-days', '2', '--cycle-max-day', '600']).text;
  assert.match(growthText, /profit \$1,000\.00, largest day \$600\.00 \(60\.0% of the profit\), 2 qualifying days/);
  const help = run(['--help']).text;
  assert.match(help, /--cycle-max-day M\s+largest profitable day since the last payout\. Growth and Lightning \(consistency rule\)\s+require it when B > S, when N > 0, or before the first payout when H > \$50,000;\s+Select Flex uses it only to check N; Select Daily ignores it/);
  assert.match(help, /an unquoted \$49,000 reaches the planner as 9,000/);
});

test('start state: an unlocked floor away from H - 2000 is used as typed, with a warning', () => {
  const st = resolveStartState(rules, 'growth', { balance: 51500, floor: 49800, highEod: 51500, qualDays: 2, cycleMaxDay: 700 });
  assert.equal(st.expectedFloor, 49500);
  assert.equal(st.warnings.length, 1);
  assert.match(st.warnings[0], /--floor \$49,800\.00 differs by \$300\.00 from --high-eod \$51,500\.00 - \$2,000\.00 = \$49,500\.00/);
  assert.equal(growth(st).floor, 49800);
  const near = resolveStartState(rules, 'growth', { balance: 51500, floor: 49800.99, highEod: 51800, qualDays: 2, cycleMaxDay: 700 });
  assert.deepEqual(near.warnings, [], 'within $1: no warning');
  // Without --high-eod, an unlocked floor gives it: H = F + 2000.
  const inferred = resolveStartState(rules, 'growth', { balance: 51500, floor: 49800, qualDays: 2, cycleMaxDay: 700 });
  assert.equal(inferred.highEod, 51800);
  assert.equal(inferred.expectedFloor, 49800);
  assert.deepEqual(inferred.warnings, []);
  // A floor below B - 2000 cannot come from any H >= B: still a warning, the floor is used as typed.
  const low = resolveStartState(rules, 'growth', { balance: 51500, floor: 49000, qualDays: 2, cycleMaxDay: 700 });
  assert.equal(low.highEod, 51500);
  assert.match(low.warnings[0], /differs by \$500\.00 from --high-eod \$51,500\.00 \(not given: the largest of --balance, the \$50,000\.00 start balance and --floor \+ \$2,000\.00\) - \$2,000\.00 = \$49,500\.00/);
});

test('start state: the ledger starts at the given balance, floor, cycle and counts', () => {
  const L = growth({ balance: 51500, floor: 49800, highEod: 51800, qualDays: 3, cycleMaxDay: 600 });
  assert.equal(L.status, ACTIVE);
  assert.equal(balance(L), 51500);
  assert.equal(L.realized, 1500);
  assert.equal(L.floor, 49800);
  assert.equal(L.locked, false);
  assert.equal(L.maxEodProfit, 1800);
  assert.equal(contractCap(L), 4);
  assert.equal(L.dll, 1250);
  assert.equal(L.qualDays, 3);
  assert.equal(L.cycleProfit, 1500);
  assert.equal(L.cycleMaxDay, 600);
  assert.equal(L.payouts, 0);
  assert.equal(L.start.balance, 51500);
  const c = payoutCheck(L);
  assert.equal(c.eligible, false);
  assert.deepEqual(Object.entries(c.checks).filter(([, ok]) => !ok).map(([k]) => k), ['days', 'consistency', 'balance']);
  assert.deepEqual(payoutBlockers(L, c).map((b) => b.check), ['days', 'consistency', 'balance']);
  assert.match(payoutBlockers(L)[0].message, /^2 more qualifying days \(profit above \$150\.00\): 3 of 5 since the last payout$/);
  assert.match(payoutBlockers(L)[2].message, /balance \$51,500\.00 is below the \$53,000\.00 minimum \(\$1,500\.00 short\)/);

  day(L, 400); // 51900: floor trails from the typed floor to 49900, 4 qualifying days, 600 / 1900 = 31.6%
  assert.equal(L.floor, 49900);
  assert.equal(L.qualDays, 4);
  day(L, 600); // 52500: locks by EOD, 5 qualifying days, balance still short
  assert.equal(L.locked, true);
  assert.equal(L.lockedBy, 'eod');
  assert.equal(L.floor, D.lockedFloor);
  assert.deepEqual(payoutBlockers(L).map((b) => b.check), ['balance']);
  assert.equal(day(L, 500), 1500, '53000: payout 1 at the $1,500 cap');
  assert.equal(L.qualDays, 0);
  assert.equal(L.cycleProfit, 0);
  assert.equal(payoutsMade(L), 1);
  assert.equal(L.payoutHistory[0].balanceAfter, 51500);
  // The same days on a fresh account pay nothing yet: the start state carried the earlier sessions.
  const F = makeFundedLedger(rules, 'growth');
  assert.deepEqual(days(F, [400, 600, 500]), [0, 0, 0]);
});

test('start state: a large largest day blocks the payout until the profit catches up (35%)', () => {
  const st = { balance: 53500, floor: 50100, highEod: 53500, qualDays: 6, cycleMaxDay: 1500 };
  const L = growth(st);
  const c = payoutCheck(L);
  assert.equal(c.eligible, false);
  const blockers = payoutBlockers(L, c);
  assert.deepEqual(blockers.map((b) => b.check), ['consistency']);
  // 1500 / 0.35 = 4285.714..., so the profit since the last payout must reach 4285.72: 785.72 more.
  assert.match(blockers[0].message, /largest day \$1,500\.00 is 42\.9% of the \$3,500\.00 profit since the last payout \(limit 35%\): \$785\.72 more profit without a larger day/);
  assert.equal(requestIfEligible(L), 0);
  assert.equal(day(L, 785.71), 0, 'one cent short');
  assert.equal(payoutCheck(L).checks.consistency, false);
  assert.equal(day(growth(st), 785.72), 1500, 'exactly enough');
  // A larger day than the typed one raises the bar: 2000 / 5500 = 36.4%, needs 5714.29.
  const B = growth(st);
  assert.equal(day(B, 2000), 0);
  assert.equal(B.cycleMaxDay, 2000);
  assert.match(payoutBlockers(B)[0].message, /largest day \$2,000\.00 is 36\.4% .*: \$214\.29 more profit/);
  assert.equal(day(B, 214.29), 1500, '2000 <= 35% of 5714.29');
  // Non-positive profit since the last payout with a typed largest day.
  const N = growth({ balance: 49900, floor: 48000, qualDays: 1, cycleMaxDay: 700 });
  assert.match(payoutBlockers(N).find((b) => b.check === 'consistency').message, /is -\$100\.00: the 35% consistency rule needs it positive and reach \$2,000\.00/);
});

test('start state: the next cap follows the payouts already taken (caps[K], then the last tier)', () => {
  const caps = rules.plans.growth.payout.caps;
  for (const [K, cap] of [[0, caps[0]], [1, caps[1]], [2, caps[2]], [3, caps[3]], [4, caps[3]], [9, caps[3]]]) {
    const st = K === 0 ? READY : { ...READY, balance: 55000, highEod: 56000, cycleStart: 52000, payoutsTaken: K };
    const L = growth(st);
    const c = payoutCheck(L);
    assert.equal(c.n, K + 1, `K=${K}`);
    assert.equal(c.cap, cap, `K=${K}`);
    assert.equal(c.eligible, true, `K=${K}`);
    assert.equal(requestIfEligible(L), cap, `K=${K}: paid at once`);
    assert.equal(L.payouts, K + 1);
    assert.equal(payoutsMade(L), 1, 'only the new payout counts');
    assert.equal(L.payoutHistory[0].n, K + 1);
  }
  // The cycle starts at the balance right after the last payout, not at 50000: 600 / (53500 - 52000) = 40%.
  const cyc = growth({ balance: 53500, floor: 50100, highEod: 55000, cycleStart: 52000, qualDays: 5, cycleMaxDay: 600, payoutsTaken: 1 });
  assert.equal(cyc.cycleProfit, 1500);
  assert.deepEqual(payoutBlockers(cyc).map((b) => b.check), ['consistency']);
  assert.match(payoutBlockers(cyc)[0].message, /\$600\.00 is 40\.0% of the \$1,500\.00 profit/);
  // Amount still bounded by balance - floor - 0.01.
  const tight = growth({ ...READY, balance: 53000, highEod: 54000, cycleStart: 50500, qualDays: 5, cycleMaxDay: 800, payoutsTaken: 3 });
  assert.equal(payoutCheck(tight).maxAmount, 2899.99);
  // Lightning: the consistency share and goal follow K too.
  const lt = resolveStartState(rules, 'lightning', { balance: 52500, floor: 50100, highEod: 53000, cycleStart: 50500, cycleMaxDay: 600, payoutsTaken: 2 });
  const LL = makeFundedLedger(rules, 'lightning', { startState: lt });
  const lc = payoutCheck(LL);
  assert.equal(lc.n, 3);
  assert.equal(lc.goal, 2000);
  assert.equal(lc.consistencyShare, 0.3);
  assert.equal(lc.eligible, true, '600 / 2000 = 30%');
  assert.match(payoutBlockers(makeFundedLedger(rules, 'lightning', { startState: { balance: 51000, floor: 49000, cycleMaxDay: 300 } }))[0].message, /below the \$3,000\.00 goal for payout 1 \(\$2,000\.00 short\)/);
});

test('start state: a locked floor stays at 50100 and must be typed as such', () => {
  const byEod = resolveStartState(rules, 'growth', { balance: 52000, floor: 50100, highEod: 52100, qualDays: 2, cycleMaxDay: 800 });
  assert.equal(byEod.locked, true);
  assert.equal(byEod.lockedBy, 'eod');
  const byPay = resolveStartState(rules, 'select-flex', { balance: 51000, floor: 50100, highEod: 51900, cycleStart: 50500, payoutsTaken: 1 });
  assert.equal(byPay.locked, true);
  assert.equal(byPay.lockedBy, 'payout', 'a payout request locked it before any EOD balance reached 52100');
  const unlocked = resolveStartState(rules, 'growth', { balance: 52000, floor: 50000, highEod: 52099.99, qualDays: 2, cycleMaxDay: 800 });
  assert.equal(unlocked.locked, false);
  assert.throws(() => resolveStartState(rules, 'growth', { balance: 52000, floor: 50000, highEod: 52100, cycleMaxDay: 800 }), /--floor must be the locked floor \$50,100\.00 \(--high-eod \$52,100\.00 reached \$52,100\.00\), got \$50,000\.00/);
  assert.throws(() => resolveStartState(rules, 'growth', { balance: 51000, floor: 49000, cycleStart: 50500, cycleMaxDay: 300, payoutsTaken: 1 }), /locked floor .*a payout was requested/);

  const L = growth(byEod);
  assert.equal(L.dll, 1250, 'start balance 52000: DLL not raised');
  day(L, 3000); // 55000
  assert.equal(L.floor, D.lockedFloor, 'never trails once locked');
  assert.equal(L.dll, 2000, 'a 55000 close raises it from the next session');
  const T = growth({ balance: 51000, floor: 50100, highEod: 52200, qualDays: 2, cycleMaxDay: 800 });
  startDay(T, 1);
  assert.equal(stepTrade(T, 0, -899.99, -100), ACTIVE);
  assert.equal(stepTrade(T, 0, -800, -100), BREACHED, 'net liquidation 50100 touches the locked floor');
});

test('start state: DLL raised once a close reached 53000 (--high-eod), as in the ledger', () => {
  assert.equal(growth(READY).dll, 2000);
  assert.equal(growth(READY).dllRaised, true);
  const below = resolveStartState(rules, 'growth', { balance: 52800, floor: 50100, highEod: 53200, qualDays: 4, cycleMaxDay: 900 });
  assert.equal(below.dllRaised, true, 'H 53200: the ledger raised it at that close and keeps it');
  assert.equal(below.dll, 2000);
  assert.equal(below.notes.length, 1);
  assert.match(below.notes[0], /^DLL \$2,000\.00: a close reached \$53,000\.00 by --high-eod \$53,200\.00, and the planner keeps that once reached/);
  // A fresh account that pays out at 53000 and drops to 51500 keeps the 2000 DLL; the same state typed in does too.
  const F = makeFundedLedger(rules, 'growth');
  assert.deepEqual(days(F, [600, 600, 600, 600, 600]), [0, 0, 0, 0, 1500]);
  assert.equal(balance(F), 51500);
  const typed = growth({ balance: 51500, floor: 50100, highEod: 53000, cycleStart: 51500, payoutsTaken: 1 });
  assert.equal(typed.dll, F.dll);
  assert.equal(typed.dll, 2000);
  const never = resolveStartState(rules, 'growth', { balance: 52000, floor: 50100, highEod: 52500, qualDays: 2, cycleMaxDay: 800 });
  assert.equal(never.dll, 1250);
  assert.deepEqual(never.notes, [], 'never reached');
  const L = growth(never);
  day(L, 1000); // 53000 close: raised from the next session, as for a fresh account
  assert.equal(L.dll, 2000);
  assert.equal(makeFundedLedger(rules, 'growth', { legacy: true, startState: READY }).dll, null, 'legacy Growth: removed at 53000');
  assert.equal(makeFundedLedger(rules, 'select-daily', { startState: { balance: 53000, floor: 50100 } }).dll, 1000, 'Select Daily: no raise');
  // Select scaling comes from the highest EOD profit.
  assert.equal(contractCap(makeFundedLedger(rules, 'select-flex', { startState: { balance: 51000, floor: 49600, highEod: 51600 } })), 3);
  assert.equal(contractCap(makeFundedLedger(rules, 'select-flex', { startState: { balance: 50500, floor: 48500 } })), 2);
});

/** Empirical source whose every session is one closed +pnl trade. */
function flatSource(pnl) {
  const trades = ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'].map((dayKey, i) => ({
    tradeNo: i + 1,
    dayKey,
    entryTime: new Date(`${dayKey}T14:00:00Z`),
    exitTime: new Date(`${dayKey}T15:00:00Z`),
    contracts: 1,
    pnl,
    pnlPer: pnl,
    mfePer: pnl > 0 ? pnl : 0,
    maePer: pnl < 0 ? pnl : 0,
  }));
  return { trades, source: () => makeEmpiricalSource(trades) };
}

test('start state: a state equal to a fresh account simulates exactly like a fresh account', () => {
  const src = () =>
    makeParametricSource({ winRate: 0.47, avgWinR: 1.8, riskPerContract: 150, tradesPerDay: 2, costPerContract: 1.34, rSpread: 0.5 });
  for (const plan of ['growth', 'select-flex', 'select-daily', 'lightning']) {
    const opts = { contracts: 2, runs: 300, horizonDays: 60, seed: 5 };
    const fresh = simulateFunded(rules, plan, src(), opts);
    const { fromStartState, payoutsBefore, payoutNow, ...same } = simulateFunded(rules, plan, src(), { ...opts, startState: { balance: S, floor: S - D.amount } });
    assert.equal(fromStartState, true, plan);
    assert.equal(payoutsBefore, 0, plan);
    assert.equal(payoutNow, null, plan);
    assert.deepEqual(same, fresh, plan);
    assert.ok(fresh.pPayout > 0, `${plan} pays sometimes`);
  }
});

test('start state: the simulation counts payouts and days from the start (K taken before are not counted)', () => {
  const { source } = flatSource(600);
  // Eligible now as payout 4 ($3,000): pays at once, then every 5 sessions of +600 (54500 again, 20% consistency).
  const st = { balance: 54500, floor: 50100, highEod: 56000, cycleStart: 51500, qualDays: 5, cycleMaxDay: 1000, payoutsTaken: 3 };
  const r = simulateFunded(rules, 'growth', source(), { contracts: 1, runs: 20, horizonDays: 10, seed: 3, startState: st });
  assert.deepEqual(r.payoutNow, { n: 4, amount: 3000, toTrader: 2700 }, 'requested at once');
  assert.equal(r.pPayout, 1, 'a payout after the one now: after session 5');
  assert.equal(r.meanPayouts, 3, 'at the start, after session 5 and after session 10');
  assert.equal(r.meanRequested, 9000);
  assert.equal(r.meanReceived, 8100);
  assert.equal(r.medianDaysToFirstPayout, 5, 'the next payout after the one now');
  assert.equal(r.pBreachBeforeFirstPayout, 0);
  assert.equal(r.pBreach, 0);
  assert.equal(r.payoutsBefore, 3);
  assert.equal(r.meanEndBalance, 54500 - 3000);
  // Not eligible yet: 2 more qualifying days.
  const later = simulateFunded(rules, 'growth', source(), { contracts: 1, runs: 20, horizonDays: 10, seed: 3, startState: { ...st, qualDays: 3, balance: 53300, cycleMaxDay: 700 } });
  assert.equal(later.medianDaysToFirstPayout, 2);
  assert.equal(later.payoutNow, null);
  // A losing stream from a thin cushion breaches before the next payout.
  const lose = simulateFunded(rules, 'growth', flatSource(-500).source(), { contracts: 1, runs: 20, horizonDays: 10, seed: 3, startState: { balance: 51000, floor: 50100, highEod: 52200, qualDays: 1, cycleMaxDay: 900 } });
  assert.equal(lose.pBreachBeforeFirstPayout, 1);
  assert.equal(lose.meanPayouts, 0);
  const nowThenLose = simulateFunded(rules, 'growth', flatSource(-500).source(), { contracts: 1, runs: 20, horizonDays: 10, seed: 3, startState: READY });
  assert.deepEqual(nowThenLose.payoutNow, { n: 1, amount: 1500, toTrader: 1350 });
  assert.equal(nowThenLose.meanPayouts, 1, 'only the payout now');
  assert.equal(nowThenLose.pPayout, 0, 'no payout after it');
  assert.equal(nowThenLose.pBreachBeforeFirstPayout, 1, 'breached before the next one');
  assert.equal(nowThenLose.medianDaysToFirstPayout, null);
});

test('start state: the replay starts its first account from the state, later accounts fresh', () => {
  const mk = (i, dayKey, pnl) => ({
    tradeNo: i,
    dayKey,
    entryTime: new Date(`${dayKey}T14:00:00Z`),
    exitTime: new Date(`${dayKey}T15:00:00Z`),
    contracts: 1,
    pnl,
    pnlPer: pnl,
    mfePer: Math.max(pnl, 0),
    maePer: Math.min(pnl, 0),
  });
  const trades = [mk(1, '2024-01-02', -1500), mk(2, '2024-01-03', 300)];
  const r = replayFunded(rules, 'growth', trades, { contracts: 1, startState: READY });
  assert.equal(r.fromStartState, true);
  assert.equal(r.total, 2);
  const [a, b] = r.accounts;
  assert.equal(a.fromStartState, true);
  assert.equal(a.firstPayoutDay, 'start', 'eligible at the start: paid before the first session');
  assert.equal(a.firstPayoutSession, 0);
  assert.equal(a.payouts, 1);
  assert.deepEqual(a.payoutHistory.map((p) => p.amount), [1500]);
  assert.equal(a.status, BREACHED, '51500 after the payout, then -1500 reaches 50000 <= 50100');
  assert.equal(b.fromStartState, undefined);
  assert.equal(b.startDay, '2024-01-03');
  assert.equal(r.last.balance, S + 300, 'the next account is a fresh one');
  assert.equal(r.payouts, 1);
  assert.equal(r.startPayouts, 1, 'that payout is the start state\'s, not one the trades earned');
  assert.equal(r.firstPayoutDay, 'start');
  const plain = replayFunded(rules, 'growth', trades, { contracts: 1 });
  assert.equal(plain.fromStartState, undefined);
  assert.equal(plain.startPayouts, undefined);
  assert.equal(plain.accounts[0].fromStartState, undefined);
});

test('rules: fundedRules entries must be known strings', () => {
  const clone = (patch) => {
    const r = structuredClone(rules);
    patch(r);
    return validateTradeifyRules(r);
  };
  assert.equal(typeof rules.fundedRules.kyc, 'string');
  assert.equal(typeof rules.fundedRules.payoutApproval, 'string');
  assert.throws(() => clone((r) => (r.fundedRules.somethingNew = 'x')), /fundedRules.somethingNew is not a rule the planner knows/);
  assert.throws(() => clone((r) => (r.fundedRules.kyc = true)), /fundedRules.kyc must be a string/);
  assert.equal(rules.unverified.length, 4);
  assert.ok(!rules.unverified.some((u) => /Growth consistency/.test(u)), 'the Growth consistency window is verified');
  assert.match(rules.plans.growth.consistencyNote, /resets after each approved payout/);
});

test('CLI: start-state options parse, validate and only apply with --firm tradeify', () => {
  assert.equal(parseStartArgs({}), null);
  assert.deepEqual(parseStartArgs({ balance: '$52,340.50', floor: '50,100' }), {
    balance: 52340.5,
    floor: 50100,
    highEod: undefined,
    cycleStart: undefined,
    qualDays: 0,
    cycleMaxDay: undefined,
    payoutsTaken: 0,
  });
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '20', '--horizon', '5', '--contracts', '1'];
  assert.throws(() => run([...base, '--balance', '52000']), /--floor is required to start from your current account \(given: --balance\); read it off/);
  assert.throws(() => run([...base, '--qual-days', '2']), /--balance and --floor are required/);
  assert.throws(() => run([...base, '--balance', '50100', '--floor', '50100']), /already breached/);
  assert.throws(() => run([...base, '--balance', '52000', '--floor', '50000']), /--cycle-max-day is required/);
  assert.throws(() => run([...base, '--balance', '52000', '--floor', '50000', '--cycle-max-day', '800', '--qual-days', '1.5']), /--qual-days must be an integer >= 0/);
  assert.throws(() => run([...base, '--balance', '52000', '--floor', '50000', '--cycle-max-day', '800', '--payouts-taken', '-1']), /--payouts-taken must be an integer >= 0/);
  assert.throws(() => run([...base, '--balance', 'abc', '--floor', '50000']), /--balance must be a number/);
  for (const k of ['--balance', '--floor', '--high-eod', '--cycle-start', '--qual-days', '--cycle-max-day', '--payouts-taken']) {
    assert.throws(() => run(['--win', '0.5', '--rr', '1', '--risk', '100', k, '1']), /only appl(y|ies) with --firm tradeify/, k);
  }
  const help = run(['--help']).text;
  for (const k of ['--balance B', '--floor F', '--high-eod H', '--cycle-start S', '--qual-days N', '--cycle-max-day M', '--payouts-taken K']) assert.ok(help.includes(k), k);
});

test('CLI: end to end from a start state (parametric source)', () => {
  const base = ['--firm', 'tradeify', '--win', '0.5', '--rr', '1.5', '--risk', '100', '--runs', '200', '--horizon', '40', '--contracts', '1,2', '--seed', '7'];
  const startFlags = ['--balance', '52,800', '--floor', '50100', '--high-eod', '53200', '--qual-days', '4', '--cycle-max-day', '900'];
  const out = run([...base, ...startFlags, '--json']).data;
  const st = out.startState;
  assert.equal(st.balance, 52800);
  assert.equal(st.floor, 50100);
  assert.equal(st.roomToFloor, 2700);
  assert.equal(st.cycleProfit, 2800);
  assert.equal(st.cycleMaxDay, 900);
  assert.equal(st.qualDays, 4);
  assert.equal(st.locked, true);
  assert.equal(st.dll, 2000, 'a close reached 53000 (--high-eod 53200)');
  assert.equal(st.nextPayout, 1);
  assert.equal(st.nextCap, 1500);
  assert.equal(st.payoutNow.eligible, false);
  assert.deepEqual(st.payoutNow.blockers.map((b) => b.check), ['days', 'balance']);
  assert.equal(st.notes.length, 1, 'DLL note');
  assert.deepEqual(st.alsoNeeded.map((a) => a.rule), ['microscalping', 'kyc', 'payoutApproval']);
  assert.equal(st.alsoNeeded[0].status, 'not checked without --trades');
  assert.equal(st.kind, undefined);
  assert.equal(out.results.length, 2);
  for (const r of out.results) {
    assert.equal(r.fromStartState, true);
    assert.ok(r.medianDaysToFirstPayout >= 1, 'one more qualifying day and $200 more balance are needed');
  }
  const fresh = run([...base, '--json']).data;
  assert.equal(fresh.startState, undefined, 'no start state without the options');
  assert.equal(fresh.results[0].fromStartState, undefined);
  assert.ok(out.results[0].pPayout > fresh.results[0].pPayout, 'a start near the payout reaches it more often than a fresh account');

  const text = run([...base, ...startFlags]).text;
  const lines = text.split('\n');
  const startAt = lines.findIndex((l) => l.startsWith('Start  : your account now: balance $52,800.00, floor $50,100.00 (locked at $50,100'));
  const tableAt = lines.findIndex((l) => l.startsWith('FUNDED ACCOUNT from the start state above (40 more trading sessions'));
  assert.ok(startAt > 0 && tableAt > startAt, 'start state above the table');
  assert.match(text, /room to floor \$2,700\.00; DLL \$2,000 \(raised\)/);
  assert.match(text, /profit \$2,800\.00, largest day \$900\.00 \(32\.1% of the profit\), 4 qualifying days \(5 needed\); 0 payouts taken, next is payout 1, cap \$1,500/);
  assert.match(text, /payout now: no - 1 more qualifying day \(profit above \$150\.00\): 4 of 5 since the last payout; balance \$52,800\.00 is below the \$53,000\.00 minimum \(\$200\.00 short\)/);
  assert.match(text, /also needed \(not modelled\): more than 50% of trades .* \(not checked without --trades\); identity verification \(KYC\)/);
  assert.match(text, /note: DLL \$2,000\.00: a close reached \$53,000\.00 by --high-eod \$53,200\.00, and the planner keeps that/);
  assert.doesNotMatch(text, /requested now/, 'not eligible now');
  assert.match(text, /P\(1\+ more payout\) .* P\(breach<next pay\) .* Days to next pay/);
  assert.match(text, /Summary: Growth 50K Funded from your account now \(balance \$52,800\.00, floor \$50,100\.00, next payout 1\): /);
  assert.doesNotMatch(run(base).text, /Start  :|from your account now|next pay/, 'unchanged without a start state');

  const ready = run([...base, '--balance', '54500', '--floor', '50100', '--high-eod', '56000', '--cycle-start', '51500', '--qual-days', '5', '--cycle-max-day', '1000', '--payouts-taken', '3']);
  assert.match(ready.text, /payout now: yes, \$3,000\.00 \(payout 4\); the run requests it at once, before the first simulated session; the next-payout columns below count the payouts after it/);
  assert.match(ready.text, /Payouts, Requested and To trader include the \$3,000\.00 payout 4 requested now \(same in every run\); P\(1\+ more payout\), P\(breach<next pay\) and Days to next pay count only the payouts after it/);
  assert.match(ready.text, /Days to next pay = median trading sessions from now to the next payout after the one requested now/);
  assert.match(ready.text, /reach at least one more payout after the \$3,000\.00 payout 4 requested now, [\d.]+% breach before it/);
  assert.doesNotMatch(ready.text, /KYC/, 'KYC is a first-payout gate only');
  assert.equal(ready.data.startState.nextCap, 3000);
  assert.deepEqual(ready.data.startState.payoutNow.blockedBy, [], 'no --trades: the 10-second rule is not checked');
  for (const r of ready.data.results) {
    assert.deepEqual(r.payoutNow, { n: 4, amount: 3000, toTrader: 2700 });
    assert.ok(r.pPayout < 1, 'the payout now is not counted as the next one');
    assert.ok(r.medianDaysToFirstPayout == null || r.medianDaysToFirstPayout >= 1);
    assert.ok(r.meanPayouts >= 1, 'the payout now is in the counts');
    assert.equal(r.payoutsBefore, 3);
  }
  const warn = run([...base, '--balance', '51500', '--floor', '49800', '--high-eod', '51500', '--qual-days', '2', '--cycle-max-day', '700']).text;
  assert.match(warn, /WARNING: --floor \$49,800\.00 differs by \$300\.00/);
  assert.match(warn, /trails \$2,000 below the highest end-of-day balance \$51,500\.00; locks at \$50,100 once a close reaches \$52,100 or a payout is requested/);
});
