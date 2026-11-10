// Tests for journal.mjs. Run: cd trading/tradeify-50k/journal && node --test test/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as J from '../journal.mjs';

const CLI = join(dirname(fileURLToPath(import.meta.url)), '..', 'journal.mjs');
const run = (args) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8' });
const tmp = () => mkdtempSync(join(tmpdir(), 'journal-test-'));
const pad = (n) => String(n).padStart(2, '0');

/** UTC ms of a New York "YYYY-MM-DD HH:MM". */
const et = (s) => {
  const [y, m, d, h, mi] = s.split(/[- :]/).map(Number);
  return J.nyToUtc(y, m, d, h, mi);
};
/** Bars from rows [time, o, h, l, c]; a bare "HH:MM" time is on `day`. */
const bars = (day, rows) => rows.map(([t, o, h, l, c]) => ({ t: et(t.length === 5 ? `${day} ${t}` : t), o, h, l, c }));
/** Same flat bar every `step` minutes from start to end (inclusive). */
const flatBars = (day, from, to, ohlc, step = 5) => {
  const out = [];
  for (let t = et(`${day} ${from}`); t <= et(`${day} ${to}`); t += step * 60000) out.push({ t, o: ohlc[0], h: ohlc[1], l: ohlc[2], c: ohlc[3] });
  return out;
};
const DAY = '2026-10-14'; // a Wednesday, EDT
const M5 = 5 * 60000;
// Written at 09:59, so the call is live from the 10:00 bar (the minute a call is written in counts as seen).
const call = (over = {}) => J.validateCall({ id: 1, time_et: `${DAY} 09:59`, symbol: 'MNQ', side: 'long', entry: '100', stop: '90', target: '120', size: '1', mode: 'paper', note: '', ...over });
const grade = (c, b, barMs = M5, cost) => J.gradeCall(c, b, barMs, cost);

test('validation: every bad field gets a clear message', () => {
  assert.throws(() => call({ stop: '105' }), /a long's stop \(105\) must be below its entry \(100\)/);
  assert.throws(() => call({ target: '95' }), /a long's target \(95\) must be above its entry \(100\)/);
  assert.throws(() => call({ side: 'short', stop: '95', target: '80' }), /a short's stop \(95\) must be above its entry/);
  assert.throws(() => call({ side: 'short', stop: '110', target: '105' }), /a short's target \(105\) must be below its entry/);
  assert.throws(() => call({ side: 'buy' }), /side must be long or short, got "buy"/);
  for (const size of ['0', '-1', '1.5', 'two', '']) assert.throws(() => call({ size }), /size must be a whole number of contracts/);
  assert.throws(() => call({ size: '41' }), /above the Growth 50K limit/);
  assert.throws(() => call({ symbol: 'NQ', size: '5' }), /above the Growth 50K limit/);
  assert.throws(() => call({ symbol: 'ES' }), /symbol must be MNQ or NQ, got "ES"/);
  assert.throws(() => call({ mode: 'sim' }), /mode must be paper or live/);
  assert.throws(() => call({ entry: '100.1' }), /entry 100.1 is not a whole tick/);
  assert.throws(() => call({ entry: 'abc' }), /entry must be a price above 0/);
  assert.throws(() => call({ time_et: '10/14/2026 10:00' }), /must look like "2026-10-14 13:05"/);
  assert.throws(() => call({ time_et: '2026-02-30 10:00' }), /not a real date and time/);
  assert.throws(() => call({ time_et: `${DAY} 17:15` }), /between the 16:45 ET flat-by and the 18:00 ET session start/);
  assert.throws(() => call({ time_et: `${DAY} 16:45` }), /between the 16:45 ET flat-by/);
  assert.throws(() => call({ time_et: '2026-10-17 10:00' }), /outside the futures week/); // Saturday
  assert.throws(() => call({ time_et: '2026-10-16 18:30' }), /outside the futures week/); // Friday evening
  assert.throws(() => call({ time_et: '2026-03-08 02:30' }), /does not exist in New York/);
  assert.throws(() => call({ stop: '110', target: '90' }), (e) => e.message.split('\n').length === 2); // all problems at once
  const ok = call({ symbol: 'nq', side: 'LONG', mode: 'Live', time_et: '2026-10-18 18:00' }); // Sunday evening opens Monday
  assert.deepEqual([ok.symbol, ok.side, ok.mode, ok.session], ['NQ', 'long', 'live', '2026-10-19']);
  // the add stamp at the end of the note says when the call was written
  assert.deepEqual([call().added_et, call().backfilled], [null, false]);
  const later = call({ time_et: `${DAY} 10:00`, note: 'fade [added 2026-10-14 10:01 ET]' });
  assert.deepEqual([later.added_et, later.backfilled], [`${DAY} 10:01`, true]);
  assert.equal(call({ time_et: `${DAY} 10:00`, note: '[added 2026-10-14 10:00 ET]' }).backfilled, false, 'same minute is not hindsight');
});

test('add: stamps each call, defaults to the current minute, refuses a past time without --backfill, leaves the file alone on errors', () => {
  const file = join(tmp(), 'calls.csv');
  const base = ['add', '--calls', file];
  const short = ['--time', '2026-10-14 13:05', '--side', 'short', '--entry', '30262.50', '--stop', '30320.50', '--target', '30175.25', '--note', 'pullback, "clean"'];
  let r = run([...base, ...short]);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /time 2026-10-14 13:05 is before now \(.* ET\)\. A call written after the move is hindsight: leave --time out .* or add --backfill/);
  assert.equal(existsSync(file), false);
  r = run([...base, ...short, '--backfill']);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /Added call 1 .*short 1 MNQ \(paper\)/);
  assert.match(r.stdout, /58\.00 pts, \$116\.00 risk.*reward:risk 1\.50/);
  assert.match(r.stderr, /Backfilled: this call's time is \d+ days before now\. It is stamped \[added \d{4}-\d\d-\d\d \d\d:\d\d ET\]; the score lists it but leaves it out/);
  r = run([...base, '--time', '2026-10-21 14:05', '--side', 'long', '--entry', '30053.5', '--stop', '30033.5', '--target', '30082.5', '--size', '2', '--symbol', 'nq', '--mode', 'live', '--backfill']);
  assert.equal(r.status, 0, r.stderr);
  const before = readFileSync(file, 'utf8');
  const lines = before.split('\n');
  assert.equal(lines.length, 4);
  assert.equal(lines[0], 'id,time_et,symbol,side,entry,stop,target,size,mode,note');
  assert.match(lines[1], /^1,2026-10-14 13:05,MNQ,short,30262\.50,30320\.50,30175\.25,1,paper,"pullback, ""clean"" \[added \d{4}-\d\d-\d\d \d\d:\d\d ET\]"$/);
  assert.match(lines[2], /^2,2026-10-21 14:05,NQ,long,30053\.50,30033\.50,30082\.50,2,live,\[added \d{4}-\d\d-\d\d \d\d:\d\d ET\]$/);
  assert.equal(lines[3], '');
  const back = J.readCalls(file);
  assert.match(back[0].note, /^pullback, "clean" \[added /);
  assert.deepEqual(back.map((c) => c.backfilled), [true, true]);

  r = run([...base, '--time', '2026-10-21 14:05', '--side', 'long', '--entry', '30053.50', '--stop', '30060', '--target', '30082.50', '--backfill']);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /journal: a long's stop \(30060\) must be below its entry \(30053\.5\)/);
  assert.equal(readFileSync(file, 'utf8'), before);

  assert.match(run([...base, '--side', 'long']).stderr, /add needs --entry --stop --target/);
  assert.match(run([...base, '--time']).stderr, /--time needs a value/);
  assert.match(run(['score', '--calls', file, '--bars', file, '--colour', 'red']).stderr, /score has no option --colour/);
  assert.match(run(['trade']).stderr, /unknown command "trade"/);
  assert.match(run(['score', '--calls', file, '--bars', join(tmp(), 'none.csv')]).stderr, /bars file .* not found/);

  // With a fixed clock: 13:09:59 with --time 13:05 is refused (the old check let up to 5.5 minutes of hindsight through).
  const file2 = join(tmp(), 'calls.csv');
  const longCall = { calls: file2, side: 'long', entry: '1', stop: '0.5', target: '2' };
  assert.throws(() => J.addCall({ ...longCall, time: '2026-10-14 13:05' }, et('2026-10-14 13:09') + 59000), /2026-10-14 13:05 is before now \(2026-10-14 13:09 ET\)/);
  assert.equal(existsSync(file2), false);
  // no --time: the current minute, stamped, no warning
  const { call: c, warning } = J.addCall(longCall, et('2026-10-14 13:04') + 30000);
  assert.deepEqual([c.id, c.time_et, c.note, c.backfilled, warning], [1, '2026-10-14 13:04', '[added 2026-10-14 13:04 ET]', false, null]);
  assert.match(J.addCall(longCall, et('2026-10-14 13:04')).message, /Graded from the first bar that opens after 13:04 ET/);
  // written ahead of its time is fine
  assert.equal(J.addCall({ ...longCall, time: '2026-10-14 13:30' }, et('2026-10-14 13:04')).call.backfilled, false);
  // too close to the flat-by to fill
  assert.match(J.addCall({ ...longCall, time: '2026-10-14 16:41' }, et('2026-10-14 16:41')).warning, /a call after 16:39 cannot fill on 5-minute bars/);
  assert.equal(J.addCall({ ...longCall, time: '2026-10-14 16:39' }, et('2026-10-14 16:39')).warning, null);
});

test('readCalls: points at the bad line', () => {
  const dir = tmp();
  const f = (name, text) => { const p = join(dir, name); writeFileSync(p, text); return p; };
  const head = 'id,time_et,symbol,side,entry,stop,target,size,mode,note\n';
  assert.throws(() => J.readCalls(f('a.csv', 'id,time,side\n')), /the first line must be id,time_et/);
  assert.throws(() => J.readCalls(f('b.csv', `${head}1,2026-10-14 10:00,MNQ,long,100,90,120,1,paper,a, b\n`)), /line 2: expected 10 fields, found 11/);
  assert.throws(() => J.readCalls(f('c.csv', `${head}1,2026-10-14 10:00,MNQ,long,100,90,120,1,paper,\n1,2026-10-14 10:00,MNQ,long,100,90,120,1,paper,\n`)), /line 3: id 1 is used twice/);
  assert.throws(() => J.readCalls(f('d.csv', `${head}\n7,2026-10-14 10:00,MNQ,long,100,110,120,1,paper,\n`)), /line 3 \(call 7\): a long's stop/);
});

test('fill: on the first bar, later in the 30-minute window, not filled, bars end, no data, too late', () => {
  let r = grade(call(), bars(DAY, [['10:00', 101, 102, 99.75, 101.5], ['10:05', 101.5, 121, 101, 120]]));
  assert.deepEqual([r.status, r.fill_et, r.exit_et, r.exitPrice], ['TARGET', `${DAY} 10:00`, `${DAY} 10:05`, 120]);

  r = grade(call({ time_et: `${DAY} 09:58` }), bars(DAY, [['09:55', 101, 101.5, 99.5, 101], ['10:00', 103, 105, 102, 104], ['10:05', 104, 104, 101, 102], ['10:10', 102, 103, 99.5, 100.5], ['10:15', 100.5, 120.25, 100, 120]]));
  assert.deepEqual([r.status, r.fill_et, r.unseen], ['TARGET', `${DAY} 10:10`, true], 'the 09:55 bar touched 100 but had started before the call');

  const above = flatBars(DAY, '10:00', '10:25', [102, 103, 101, 102]);
  r = grade(call(), [...above, ...bars(DAY, [['10:30', 102, 102, 95, 96], ['10:35', 96, 97, 95, 96]])]);
  assert.equal(r.status, 'NOT FILLED');
  assert.match(r.detail, /did not touch 100\.00 within 30 minutes/);
  assert.equal(r.r, null);

  r = grade(call(), above.slice(0, 3));
  assert.deepEqual([r.status, r.detail], ['OPEN', 'the bars end while the call waits for its fill']);
  r = grade(call({ time_et: `${DAY} 11:00` }), above);
  assert.deepEqual([r.status, r.detail], ['OPEN', 'the bars end before this call']);
  r = grade(call({ time_et: `${DAY} 09:00` }), above);
  assert.equal(r.status, 'NO DATA');
  r = grade(call({ time_et: `${DAY} 09:00` }), [...bars(DAY, [['08:55', 102, 103, 101, 102]]), ...above]);
  assert.deepEqual([r.status, r.detail], ['NO DATA', 'no bars in the 30 minutes after the call']);

  // F11: no bar can start after the call's minute and end by 16:45 (it used to say NO DATA although bars exist)
  const close = [...flatBars(DAY, '16:30', '16:40', [100.5, 101, 99.5, 100.5]), ...bars(DAY, [['16:45', 100, 100, 100, 100], ['16:50', 100, 100, 100, 100]])];
  r = grade(call({ time_et: `${DAY} 16:41` }), close);
  assert.deepEqual([r.status, r.detail], ['TOO LATE', "no 5-minute bar starts after the call's minute and ends by the 16:45 flat-by"]);
  assert.equal(grade(call({ time_et: `${DAY} 16:39` }), close).status, 'FLAT');
  const ones = flatBars(DAY, '16:40', '16:50', [100.5, 101, 99.5, 100.5], 1);
  assert.equal(grade(call({ time_et: `${DAY} 16:43` }), ones, 60000).status, 'FLAT');
  assert.equal(grade(call({ time_et: `${DAY} 16:44` }), ones, 60000).status, 'TOO LATE');
});

test('F3: the bar the call was written in is never graded, so a dip the trader already saw cannot fill it', () => {
  // 1-minute bars; the call is stamped 10:07 and written at 10:07:50, after the 10:07 bar had touched 100.
  const c = call({ time_et: `${DAY} 10:07` });
  const one = [...bars(DAY, [['10:06', 101, 101.5, 100.75, 101], ['10:07', 101, 101.25, 100, 100.5], ['10:08', 100.5, 101.5, 100.25, 101.25], ['10:09', 101.25, 121, 101, 120]]),
    ...flatBars(DAY, '10:10', '10:40', [120, 121, 119, 120], 1)];
  const r = grade(c, one, 60000);
  assert.equal(r.status, 'NOT FILLED', 'it used to fill at 100 on the 10:07 bar and count TARGET +2R');
  assert.equal(r.unseen, false, '1-minute bars leave nothing unseen to flag');
});

test('F2: a call written inside a 5-minute bar: the rest of that bar is not graded, and both the loser and the winner are flagged', () => {
  const c = call({ time_et: `${DAY} 10:07` }); // price 101 at 10:07; the 10:05 bar runs 101.5 to 96 and closes 96.5
  const dip = ['10:05', 101, 101.5, 96, 96.5];
  const loser = [...bars(DAY, [dip, ['10:10', 96.5, 97, 93, 94], ['10:15', 94, 95, 89.75, 90.5]]), ...flatBars(DAY, '10:20', '10:40', [90.5, 92, 90, 91])];
  const winner = bars(DAY, [dip, ['10:10', 96.5, 101, 96, 100.5], ['10:15', 100.5, 121, 100, 120]]);
  const b1 = grade(c, loser), b2 = grade(c, winner);
  assert.deepEqual([b1.status, b1.unseen], ['NOT FILLED', true]);
  assert.deepEqual([b2.status, b2.fill_et, b2.unseen], ['TARGET', `${DAY} 10:10`, true]);
  for (const r of [b1, b2]) assert.match(r.detail, /the call's own 10:05 bar reached the entry \(not seen\)/);
  const s = J.summarize([b1, { ...b2, id: 2 }]);
  assert.deepEqual(s.unseen, [1, 2]);
});

test('exits: stop, target, both in one bar, and the fill bar rules', () => {
  const fill = ['10:00', 100.5, 101, 99.75, 100.25];
  let r = grade(call(), bars(DAY, [fill, ['10:05', 100.25, 100.5, 89.75, 92]]));
  assert.deepEqual([r.status, r.exitPrice, r.points, r.rGross, r.r, r.dollars], ['STOP', 90, -10, -1, -1.025, -20.5]);

  r = grade(call(), bars(DAY, [fill, ['10:05', 100.25, 101, 98, 99], ['10:10', 99, 121, 98, 119]]));
  assert.deepEqual([r.status, r.exit_et, r.points, r.rGross, r.r, r.touch], ['TARGET', `${DAY} 10:10`, 20, 2, 1.975, false]);

  r = grade(call(), bars(DAY, [fill, ['10:05', 100, 121, 89, 110]]));
  assert.deepEqual([r.status, r.exitPrice], ['STOP', 90]);
  assert.match(r.detail, /stop and target in the same bar: counted as a stop/);

  r = grade(call(), bars(DAY, [['10:00', 100.5, 101, 89.5, 95], ['10:05', 95, 121, 95, 120]]));
  assert.deepEqual([r.status, r.exit_et, r.worstOpenPnl], ['STOP', `${DAY} 10:00`, -20.5], 'worst point is the stop, not the low past it');
  assert.match(r.detail, /fill bar also reached the stop/);

  r = grade(call(), bars(DAY, [['10:00', 99, 121, 98, 120]])); // opened below the entry, rose through it to the target
  assert.deepEqual([r.status, r.exit_et], ['TARGET', `${DAY} 10:00`]);

  r = grade(call(), bars(DAY, [['10:00', 119, 122, 99.5, 101], ['10:05', 101, 101, 89, 90]])); // the target touch may have come first
  assert.equal(r.status, 'STOP');
  assert.match(r.detail, /target touch in the fill bar was ignored/);

  const short = call({ side: 'short', entry: '100', stop: '110', target: '80' });
  r = grade(short, bars(DAY, [['10:00', 99.5, 100.25, 99, 99.75], ['10:05', 99.75, 100, 79.5, 80]]));
  assert.deepEqual([r.status, r.points, r.rGross], ['TARGET', 20, 2]);
  r = grade(short, bars(DAY, [['10:00', 99.5, 100.25, 99, 99.75], ['10:05', 99.75, 110, 99, 109]]));
  assert.deepEqual([r.status, r.points, r.rGross], ['STOP', -10, -1]);

  // F8: a target that is only touched, not traded through, is marked
  r = grade(call(), bars(DAY, [fill, ['10:05', 100.25, 120, 100, 119.75]]));
  assert.deepEqual([r.status, r.touch], ['TARGET', true]);
  assert.match(r.detail, /touched exactly, not traded through/);
  assert.deepEqual(J.summarize([r]).touches, [1]);
});

test('F2/F9: price jumping over the entry between bars', () => {
  // the last close above a long limit, the next open below its stop: filled at the entry, stopped at that open
  let r = grade(call(), bars(DAY, [['09:55', 101, 102, 100.5, 101], ['10:00', 88, 92, 87, 91], ['10:05', 91, 121, 91, 120]]));
  assert.deepEqual([r.status, r.fill_et, r.fillPrice, r.exitPrice, r.points, r.rGross, r.dollars, r.worstOpenPnl], ['STOP', `${DAY} 10:00`, 100, 88, -12, -1.2, -24.5, -24.5]);
  assert.match(r.detail, /price jumped over 100\.00 at the 10:00 open: filled at the entry; it jumped past the stop too: stopped at that open/);

  // F2 A2: a long limit at 100 placed at 08:19; the 08:30 news bar opens at 85, then price comes back through 100 to 120.
  const news = bars(DAY, [['08:15', 101, 102, 100.5, 101.5], ['08:20', 101.5, 102, 100.5, 101], ['08:25', 101, 101.5, 100.25, 101],
    ['08:30', 85, 88, 84, 87], ['08:35', 87, 95, 86, 94], ['08:40', 94, 99, 93, 98], ['08:45', 98, 101, 97.5, 100.5], ['08:50', 100.5, 121, 100, 120]]);
  r = grade(call({ time_et: `${DAY} 08:19` }), news);
  assert.deepEqual([r.status, r.fill_et, r.exitPrice, r.rGross], ['STOP', `${DAY} 08:30`, 85, -1.5], 'it used to fill at 08:45 and count TARGET +2R');

  // F9: a breakout long at 100 written with price at 97, below its 98 stop, never triggers (it used to be a -1.5R STOP at 97)
  const breakout = call({ stop: '98', target: '104' });
  r = grade(breakout, [...bars(DAY, [['09:55', 97, 97.5, 96.5, 97]]), ...flatBars(DAY, '10:00', '10:35', [97, 97.5, 96.5, 97])]);
  assert.equal(r.status, 'NOT FILLED');
  // the same breakout gapping up over its entry fills at that open, the worse price
  r = grade(breakout, bars(DAY, [['09:55', 99, 99.5, 98.5, 99], ['10:00', 101, 102, 100.5, 101.5], ['10:05', 101.5, 104.25, 101, 104]]));
  assert.deepEqual([r.status, r.fillPrice, r.points, r.rGross], ['TARGET', 101, 3, 1.5]);
  assert.match(r.detail, /filled at that open, 101\.00/);

  // a short limit gapped through upward, past its stop
  r = grade(call({ side: 'short', stop: '110', target: '80' }), bars(DAY, [['09:55', 99, 99.5, 98.5, 99], ['10:00', 112, 113, 111, 112.5]]));
  assert.deepEqual([r.status, r.fillPrice, r.exitPrice, r.points], ['STOP', 100, 112, -12]);

  // a later bar gapping past the stop exits at its open
  r = grade(call(), bars(DAY, [['10:00', 100.5, 101, 99.5, 100], ['10:05', 85, 86, 84, 85.5]]));
  assert.deepEqual([r.status, r.exitPrice, r.points], ['STOP', 85, -15]);
  assert.match(r.detail, /gapped past the stop: exit at the open/);
});

test('flat at 16:45: last 5-minute bar is 16:40, last 1-minute bar is 16:44, bars ending first leave it OPEN', () => {
  const c = call({ time_et: `${DAY} 15:59` });
  const five = [...bars(DAY, [['16:00', 100, 101, 99.5, 100.5]]), ...flatBars(DAY, '16:05', '16:35', [100.5, 101, 99.5, 100.5]),
    ...bars(DAY, [['16:40', 100.5, 102.5, 100, 102], ['16:45', 102, 125, 102, 124], ['16:50', 124, 125, 123, 124]])];
  let r = grade(c, five);
  assert.deepEqual([r.status, r.exit_et, r.exitPrice, r.points, r.rGross, r.r], ['FLAT', `${DAY} 16:40`, 102, 2, 0.2, 0.175]);

  const one = [...bars(DAY, [['16:30', 100, 101, 99.5, 100.5]]), ...flatBars(DAY, '16:31', '16:43', [100.5, 101, 99.5, 100.5], 1),
    ...bars(DAY, [['16:44', 100.5, 103, 100, 103], ['16:45', 103, 125, 103, 124]])];
  r = grade(call({ time_et: `${DAY} 16:29` }), one, 60000);
  assert.deepEqual([r.status, r.exit_et, r.exitPrice], ['FLAT', `${DAY} 16:44`, 103]);

  r = grade(c, five.filter((b) => b.t <= et(`${DAY} 16:35`)));
  assert.deepEqual([r.status, r.fill_et, r.r, r.worstOpenPnl], ['OPEN', `${DAY} 16:00`, null, -1.5]);
  assert.match(r.detail, /bars end with the trade still open \(\+\$0\.50 at the last close\)/);
});

test('an evening call belongs to the next day\'s session (and DST is followed)', () => {
  const t = J.parseCallTime('2026-10-13 20:00');
  assert.equal(t.session, DAY);
  assert.equal(t.flatByMs, et(`${DAY} 16:45`));
  assert.equal(J.parseCallTime('2026-10-13 16:44').session, '2026-10-13');
  assert.equal(J.parseCallTime('2026-10-13 18:00').session, DAY);
  assert.throws(() => J.parseCallTime('2026-10-13 17:59'), /between the 16:45 ET flat-by/);
  assert.equal(new Date(J.parseCallTime('2026-10-30 10:00').flatByMs).toISOString(), '2026-10-30T20:45:00.000Z'); // EDT
  assert.equal(new Date(J.parseCallTime('2026-11-02 10:00').flatByMs).toISOString(), '2026-11-02T21:45:00.000Z'); // EST
  assert.equal(J.formatEt(Date.parse('2026-11-02T14:30:00Z')), '2026-11-02 09:30');

  const b = [...bars('2026-10-13', [['20:00', 100, 100.5, 99.75, 100.25]]), ...flatBars('2026-10-13', '20:05', '23:55', [100.25, 101, 99.5, 100.5]),
    ...flatBars(DAY, '00:00', '16:35', [100.5, 101, 99.5, 100.5]), ...bars(DAY, [['16:40', 100.5, 105.5, 100, 105], ['16:45', 105, 125, 105, 124]])];
  const r = grade(call({ time_et: '2026-10-13 19:59' }), b);
  assert.deepEqual([r.status, r.fill_et, r.exit_et, r.exitPrice], ['FLAT', '2026-10-13 20:00', `${DAY} 16:40`, 105]);
});

test('R and dollar math for MNQ and NQ, with default, single and per-symbol cost', () => {
  const b = bars(DAY, [['13:05', 30262.75, 30268.75, 30239.25, 30258.25], ['13:10', 30258.75, 30266, 30167.75, 30178]]);
  const s = call({ time_et: `${DAY} 13:04`, side: 'short', entry: '30262.50', stop: '30320.50', target: '30175.25', size: '2' });
  let r = grade(s, b);
  assert.equal(r.status, 'TARGET');
  assert.equal(r.points, 87.25);
  assert.equal(r.rGross, 87.25 / 58);
  assert.equal(r.dollars, 87.25 * 2 * 2 - 0.5 * 2); // 348
  assert.equal(r.r, 348 / (58 * 2 * 2)); // after commissions
  assert.equal(r.worstOpenPnl, -(6.25 * 2 * 2 + 0.5 * 2)); // highest high 30268.75 is 6.25 pts against
  assert.equal(r.plannedRR, 87.25 / 58);

  const nq = call({ symbol: 'NQ' });
  const stopBars = bars(DAY, [['10:00', 100.5, 101, 99.75, 100.25], ['10:05', 100.25, 100.5, 89.75, 92]]);
  r = grade(nq, stopBars, M5, J.SYMBOLS.NQ.cost);
  assert.deepEqual([r.points, r.rGross, r.r, r.dollars, r.worstOpenPnl], [-10, -1, -1.0075, -201.5, -201.5]);
  const data = { bars: stopBars, barMs: M5 };
  assert.equal(J.scoreCalls([nq], data, { cost: 0 }).results[0].dollars, -200);
  assert.equal(J.scoreCalls([nq], data).results[0].dollars, -201.5);
  // F13: an MNQ-only cost leaves NQ at its own default
  assert.equal(J.scoreCalls([nq], data, { cost: { MNQ: 0.5 } }).results[0].dollars, -201.5);
  assert.equal(J.scoreCalls([nq], data, { cost: { NQ: 3 } }).results[0].dollars, -203);
  assert.deepEqual(J.parseCost('MNQ=0.6, nq=2'), { MNQ: 0.6, NQ: 2 });
  assert.equal(J.parseCost('0.5'), 0.5);
  assert.throws(() => J.parseCost('ES=1'), /--cost must be a dollar amount \(0\.5\) or one per symbol/);
  assert.deepEqual(J.resolveCosts({ NQ: 2 }), { MNQ: 0.5, NQ: 2 });
});

test('F4: commissions count, so 40 MNQ scalps with a 1-point stop and a 0.25-point target are not an edge', () => {
  const scalp = call({ stop: '99', target: '100.25' });
  const win = grade(scalp, bars(DAY, [['10:00', 100.25, 100.25, 100, 100], ['10:05', 100, 100.5, 100, 100.5]]));
  assert.deepEqual([win.status, win.points, win.rGross, win.dollars, win.r], ['TARGET', 0.25, 0.25, 0, 0]);
  const loss = grade(scalp, bars(DAY, [['10:00', 100.25, 100.25, 100, 100], ['10:05', 100, 100, 98.75, 99]]));
  assert.deepEqual([loss.status, loss.dollars, loss.r], ['STOP', -2.5, -1.25]);
  const rows = Array.from({ length: 40 }, (_, i) => ({ ...(i < 38 ? win : loss), id: i + 1, time_et: `${DAY} 11:${pad(i)}`, ms: et(`${DAY} 11:${pad(i)}`), marks: null }));
  const s = J.summarize(rows);
  assert.deepEqual([s.ideas, s.wins, s.totalDollars], [40, 0, -5]);
  assert.equal(s.avgRGross, 0.1875);
  assert.ok(s.avgR < 0);
  assert.doesNotMatch(s.verdict, /Edge shown/, 'it used to say "Edge shown" with a +0.09 to +0.25 interval');
});

test('bootstrap interval is seeded and reproducible', () => {
  const rs = [-1, -1, 2, 1.5, -1, 0.5, -1, 2.2, -0.4, 1];
  const a = J.bootstrapMeanCI(rs), b = J.bootstrapMeanCI(rs);
  assert.deepEqual(a, b);
  assert.ok(a.lo < 0.28 && 0.28 < a.hi, 'brackets the sample mean');
  assert.notDeepEqual(J.bootstrapMeanCI(rs, { seed: 2 }), a);
  assert.deepEqual(J.bootstrapMeanCI([1, 1, 1]), { lo: 1, hi: 1 });
  assert.equal(J.bootstrapMeanCI([]), null);
  // pinned values: a change to the resampling would show up here
  assert.deepEqual([a.lo, a.hi].map((x) => x.toFixed(4)), PINNED_CI);
});
const PINNED_CI = ['-0.4800', '1.0600']; // normal approximation: 0.28 +/- 1.96 x 0.396 = -0.50 to 1.06

/** A graded row; its open P&L is `worstOpenPnl` at its time and `dollars` one millisecond later, when it exits. */
const result = (id, r, dollars, worstOpenPnl, status = r > 0 ? 'TARGET' : 'STOP') => {
  const time_et = `${DAY} 10:${pad(id)}`, ms = et(time_et);
  return {
    id, time_et, ms, side: 'long', entry: 100, stop: 90, symbol: 'MNQ', size: 1, status, r, rGross: r, dollars, riskDollars: 20, worstOpenPnl, plannedRR: 1.5,
    marks: worstOpenPnl == null ? null : [[ms, worstOpenPnl], [ms + 1, dollars]],
  };
};

test('room check: bar by bar, overlapping calls add up, a filled call still open counts, the walk stops at the first breach, the $2,000 cap', () => {
  // A long that dips 100 points ($200.50 with cost) before reaching its target: breaches $199 of room on open P&L.
  const c = call({ entry: '30000', stop: '29880', target: '30100' });
  const b = bars(DAY, [['10:00', 30000, 30005, 29995, 30002], ['10:05', 30002, 30003, 29900, 29910], ['10:10', 29910, 30100, 29905, 30090]]);
  const { results, summary } = J.scoreCalls([c], { bars: b, barMs: M5 }, { room: 199 });
  assert.deepEqual([results[0].status, results[0].dollars, results[0].worstOpenPnl, results[0].touch], ['TARGET', 199.5, -200.5, true]);
  assert.deepEqual(summary.room.breach, { time_et: `${DAY} 10:05`, ids: [1], roomLeft: 199, openPnl: -200.5, legs: [{ id: 1, status: 'TARGET', dollars: 199.5 }] });
  assert.match(summary.verdict, /And these sizes breach the account: starting from \$199\.00 of room, the floor is touched on 2026-10-14 10:05 ET \(call 1 open\)\.$/);
  assert.equal(J.scoreCalls([c], { bars: b, barMs: M5 }, { room: 201 }).summary.room.breach, null);

  // F1: T1 and T2 of one idea are open together. Each alone fits $10 of room (-$6.50); together (-$13.00) they breach it.
  const split = bars(DAY, [['10:00', 100.5, 101, 99.75, 100.25], ['10:05', 100.25, 101, 97, 98], ['10:10', 98, 105.5, 98, 105], ['10:15', 105, 121, 104, 120]]);
  const legs = [call({ id: 1, target: '105' }), call({ id: 2, target: '120' })];
  let s = J.scoreCalls(legs, { bars: split, barMs: M5 }, { room: 10 }).summary;
  assert.deepEqual([s.room.breach?.time_et, s.room.breach?.ids, s.room.breach?.openPnl, s.room.together], [`${DAY} 10:05`, [1, 2], -13, [[1, 2]]]);
  assert.deepEqual([s.graded, s.ideas, s.splits], [2, 1, [[1, 2]]]);
  // combined size over 40 MNQ / 4 NQ is reported
  s = J.scoreCalls([call({ id: 1, size: '31' }), call({ id: 2, symbol: 'NQ' })], { bars: split, barMs: M5 }, { room: 5000 }).summary;
  assert.deepEqual(s.room.sizeOver, { time_et: `${DAY} 10:00`, ids: [1, 2], mnq: 41 });

  // F7: 10 MNQ long filled at 100, the 10:05 low 90.25 is -$200 with cost, and the file ends there: OPEN, but it breaches $150.
  const open = J.scoreCalls([call({ size: '10' })], { bars: bars(DAY, [['10:00', 100.5, 101, 99.75, 100.25], ['10:05', 100.25, 100.5, 90.25, 91]]), barMs: M5 }, { room: 150 });
  assert.deepEqual([open.results[0].status, open.results[0].worstOpenPnl, open.summary.graded], ['OPEN', -200, 0]);
  assert.match(open.results[0].detail, /still open \(-\$185\.00 at the last close\)/);
  assert.deepEqual([open.summary.room.breach.ids, open.summary.room.breach.openPnl, open.summary.room.stillOpen], [[1], -200, [1]]);

  // F10: four losses use the room up at call 4, and call 5 is not walked
  const losses = [1, 2, 3, 4, 5].map((i) => result(i, -1, -60.5, -60.5));
  let rc = J.roomCheck(losses, 199);
  assert.deepEqual([rc.breach.ids, rc.breach.roomLeft, rc.end, rc.lowest], [[4], 17.5, 17.5, -43]);

  rc = J.roomCheck([result(1, 3, 3000, -10), result(2, -1, -2100, -2100)], 199);
  assert.deepEqual([rc.breach.ids, rc.breach.roomLeft], [[2], 2000], 'room is capped at $2,000 after the win');
  rc = J.roomCheck([result(1, 1, 50, -5)], 199);
  assert.deepEqual([rc.breach, rc.lowest, rc.end], [null, 194, 249]);
});

test('summary and verdict: ideas, split targets, backfilled calls', () => {
  const rows = [result(1, 1.5, 100, -10), result(2, -1, -60.5, -60.5), result(3, -1, -60.5, -60.5), result(4, 0, -0.5, -5, 'FLAT'),
    { ...result(5, null, null, null), status: 'NOT FILLED' }, { ...result(6, null, null, null), status: 'OPEN' }];
  const s = J.summarize(rows, { room: 199 });
  assert.deepEqual([s.calls, s.graded, s.ideas, s.wins, s.winRate, s.totalR, s.totalDollars, s.avgDollars, s.longestLosingStreak, s.avgPlannedRR],
    [6, 4, 4, 1, 0.25, -0.5, -21.5, -21.5 / 4, 3, 1.5]);
  assert.deepEqual(s.counts, { TARGET: 1, STOP: 2, FLAT: 1, 'NOT FILLED': 1, OPEN: 1 });
  assert.match(s.verdict, /^Too few calls to judge: 4 graded, fewer than 30\. Keep writing/);
  const many = (r) => Array.from({ length: 30 }, (_, i) => result(i + 1, r(i), 0, 0));
  assert.match(J.summarize(many(() => 1)).verdict, /^Edge shown: the average R interval after commissions \(\+1\.00 to \+1\.00\) is above 0 over 30 graded calls, before slippage\.$/);
  assert.match(J.summarize(many(() => -1)).verdict, /^No edge: .* below 0/);
  assert.match(J.summarize(many((i) => (i % 2 ? 1 : -1))).verdict, /^No edge shown yet: .* includes 0/);

  // F5: 16 ideas (10 wins, 6 losses), each logged as T1 and T2, are 16 ideas, not 32 calls.
  const legs = [];
  for (let i = 0; i < 16; i++) {
    for (const leg of [1, 2]) legs.push({ ...result(1, i < 10 ? 1.5 : -1, i < 10 ? 29.5 : -20.5, -5), id: 2 * i + leg, time_et: `${DAY} 11:${pad(i)}`, ms: et(`${DAY} 11:${pad(i)}`), marks: null });
  }
  const split = J.summarize(legs);
  assert.deepEqual([split.graded, split.ideas, split.splits.length, split.splits[0]], [32, 16, 16, [1, 2]]);
  assert.match(split.verdict, /^Too few calls to judge: 16 graded \(from 32 rows: rows with the same time, side, entry and stop count once\), fewer than 30/);
  const apart = J.summarize(legs.map((g, k) => ({ ...g, time_et: `${DAY} 12:${pad(k)}` })));
  assert.match(apart.verdict, /^Edge shown/, 'the same rows as 32 separate ideas would pass');

  // F3: a call stamped as added after its time is listed but left out of every figure
  const back = J.summarize([result(1, 1.5, 100, -10), { ...result(2, -1, -60.5, -60.5), backfilled: true, added_et: `${DAY} 15:00` }]);
  assert.deepEqual([back.calls, back.graded, back.backfilled, back.totalDollars, back.unstamped], [2, 1, [2], 100, 1]);
});

// The same six bars, the 10:15 one missing, in every accepted format. The last (10:30) is left out by score.
const ROWS = [[et(`${DAY} 10:00`), 100.5, 101, 99.75, 100.25], [et(`${DAY} 10:05`), 100.25, 101, 98, 99], [et(`${DAY} 10:10`), 99, 104, 98.5, 103],
  [et(`${DAY} 10:20`), 103, 121, 102.5, 120], [et(`${DAY} 10:25`), 120, 120.5, 118, 119], [et(`${DAY} 10:30`), 119, 119.5, 117, 118]];
const iso = (ms) => new Date(ms - 4 * 3600000).toISOString().replace('.000Z', '-04:00');
const FORMATS = {
  'csv-iso': `timestamp,open,high,low,close,volume\n${ROWS.map(([t, ...p]) => [iso(t), ...p, 10].join(',')).join('\n')}\n`,
  'csv-unix': `﻿timestamp,open,high,low,close\r\n${ROWS.map(([t, ...p]) => [t / 1000, ...p].join(',')).join('\r\n')}`,
  'json-columns': JSON.stringify({ bars: { t: ROWS.map((r) => r[0] / 1000), o: ROWS.map((r) => r[1]), h: ROWS.map((r) => r[2]), l: ROWS.map((r) => r[3]), c: ROWS.map((r) => r[4]) } }),
  'json-rows': JSON.stringify(ROWS.slice().reverse().map(([t, o, h, l, c]) => ({ t: t / 1000, o, h, l, c }))),
  'json-bars-rows': JSON.stringify({ bars: ROWS.map(([t, o, h, l, c]) => ({ t: t / 1000, o, h, l, c })) }),
};
const csvOf = (rows) => `timestamp,open,high,low,close\n${rows.map((r) => r.join(',')).join('\n')}`;

test('bars: CSV (ISO or unix seconds) and TradingView JSON (columns or rows) parse the same; bar length from the median gap', () => {
  const expected = ROWS.map(([t, o, h, l, c]) => ({ t, o, h, l, c }));
  for (const [name, text] of Object.entries(FORMATS)) assert.deepEqual(J.parseBars(text, name), { bars: expected, barMs: M5 }, name);
  assert.equal(J.parseBars(csvOf([0, 1, 2, 3].map((i) => [1760450400 + i * 60, 1, 1, 1, 1]))).barMs, 60000);

  assert.throws(() => J.parseBars('timestamp,open,high,low,close\n2026-10-14T10:00:00,1,1,1,1\n2026-10-14T10:05:00,1,1,1,1', 'x.csv'), /x.csv line 2: timestamp "2026-10-14T10:00:00" needs a UTC offset/);
  assert.throws(() => J.parseBars('time,open,high,close\n1,1,1,1', 'x.csv'), /header must have timestamp,open,high,low,close/);
  assert.throws(() => J.parseBars('timestamp,open,high,low,close\n1760450400,1,1,2,1\n1760450700,1,1,1,1', 'x.csv'), /line 2: high\/low do not contain open\/close/);
  assert.throws(() => J.parseBars('timestamp,open,high,low,close\n1760450400,1,1,1,1\n1760450400,1,1,1,1'), /two bars at/);
  assert.throws(() => J.parseBars('timestamp,open,high,low,close\n1760450400,1,1,1,1\n1760454000,1,1,1,1'), /bars are 60 minutes apart; use 1- or 5-minute bars/);
  // F11: 15- and 30-minute bars leave too little of the 30-minute fill window
  assert.throws(() => J.parseBars(csvOf([0, 1, 2].map((i) => [1760450400 + i * 900, 1, 1, 1, 1]))), /bars are 15 minutes apart/);
  assert.throws(() => J.parseBars('{"bars":{"t":[1,2],"o":[1]}}', 'tv.json'), /tv.json: expected \{"bars"/);
  assert.throws(() => J.parseBars('{"bars":', 'tv.json'), /tv.json: not valid JSON/);
  // F6: bars stamped at their close put a bar at 17:00 ET, inside the CME break
  const closeStamped = csvOf([16 * 60 + 50, 16 * 60 + 55, 17 * 60].map((m) => [1760450400 + (m - 600) * 60, 1, 1, 1, 1]));
  assert.throws(() => J.parseBars(closeStamped, 'nt.csv'), /nt.csv: a bar is stamped 2025-10-14 17:00 ET, in the 17:00-18:00 ET break .* the time the bar opens/);

  // F12: files merge, oldest first; where they overlap the later file wins
  const a = { name: 'a.csv', ...J.parseBars(csvOf([[1760450400, 1, 2, 1, 2], [1760450700, 2, 2.5, 2, 2.25]])) };
  const b = { name: 'b.csv', ...J.parseBars(csvOf([[1760450700, 2, 3, 1.5, 2.75], [1760451000, 2.75, 3, 2.5, 3]])) };
  const merged = J.mergeBars([a, b]);
  assert.deepEqual([merged.bars.length, merged.barMs, merged.bars[1].h], [3, M5, 3]);
  const one = { name: 'c.csv', ...J.parseBars(csvOf([0, 1, 2].map((i) => [1760450400 + i * 60, 1, 1, 1, 1]))) };
  assert.throws(() => J.mergeBars([a, one]), /c.csv has 1-minute bars but a.csv has 5-minute bars/);
});

test('F14: a NOT FILLED entry far from every price in its window gets a wrong-contract hint', () => {
  const window = flatBars(DAY, '10:00', '10:40', [30000, 30010, 29990, 30000]);
  const far = grade(call({ entry: '29800', stop: '29760', target: '29900' }), window);
  assert.equal(far.status, 'NOT FILLED');
  assert.match(far.detail, /every price in that time was at least 190\.00 points away: is it the contract you trade \(roll week\?\) or a typo\?/);
  const near = grade(call({ entry: '29950', stop: '29910', target: '30050' }), window);
  assert.doesNotMatch(near.detail, /contract you trade/);
});

test('score CLI: same results from CSV and JSON bars, a readable report, --json, merged --bars files and per-symbol cost', () => {
  const dir = tmp();
  const calls = join(dir, 'calls.csv');
  writeFileSync(calls, ['id,time_et,symbol,side,entry,stop,target,size,mode,note',
    `1,${DAY} 10:00,MNQ,long,100,90,120,1,paper,"first, test"`, `2,${DAY} 10:00,MNQ,long,95,85,130,1,live,`, `3,${DAY} 10:00,MNQ,short,100,110,80,1,paper,`].join('\n'));
  const outs = Object.entries(FORMATS).map(([name, text]) => {
    const p = join(dir, `${name}.${name.startsWith('csv') ? 'csv' : 'json'}`);
    writeFileSync(p, text);
    const r = run(['score', '--calls', calls, '--bars', p, '--json']);
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout);
  });
  for (const o of outs) assert.deepEqual(o.calls, outs[0].calls);
  assert.deepEqual(outs[0].calls.map((c) => c.status), ['TARGET', 'NOT FILLED', 'STOP']);
  assert.deepEqual(outs[0].calls.map((c) => c.fill_et), [`${DAY} 10:05`, null, `${DAY} 10:05`], 'live from the bar after the call\'s minute');
  assert.equal(outs[0].summary.graded, 2);
  assert.deepEqual([outs[0].bars.barMinutes, outs[0].bars.last_et, outs[0].bars.left_out_et], [5, `${DAY} 10:25`, `${DAY} 10:30`]);
  assert.deepEqual(outs[0].cost, { MNQ: 0.5, NQ: 1.5 });
  assert.equal(outs[0].calls[0].marks, undefined);
  assert.deepEqual(outs[0].rules, J.RULES);

  const csv = join(dir, 'csv-iso.csv');
  let r = run(['score', '--calls', calls, '--bars', csv, '--room', '3', '--cost', '0']);
  assert.equal(r.status, 0, r.stderr);
  for (const s of ['Scoring rules:', '1. Start: a call is live', 'Stop and target in the same bar count as a STOP', 'NOT FILLED', 'win rate 50.0%',
    'the last bar in the file, 2026-10-14 10:30, is left out', 'Room to the floor before the first call: $3.00', 'Cost per contract, round trip: MNQ $0.00, NQ $0.00',
    'ACCOUNT BREACHED on 2026-10-14 10:05 ET with calls 1,3 open: open P&L -$6.00 against $3.00 of room left (they closed at +$20.00 together, but the floor had already been touched). Later bars and calls are not walked.',
    'open together: calls 1,3', 'no add stamp           3 of 3 calls', 'not seen               calls 1,3',
    'Verdict: Too few calls to judge: 2 graded, fewer than 30. Keep writing every call down before the move. And these sizes breach the account']) assert.ok(r.stdout.includes(s), s);
  assert.ok(r.stdout.indexOf('ACCOUNT BREACHED') < r.stdout.indexOf('open together: calls'), 'the breach is printed first');

  r = run(['score', '--calls', calls, '--bars', csv, '--cost', 'NQ=2.25']);
  assert.ok(r.stdout.includes('Cost per contract, round trip: MNQ $0.50, NQ $2.25'), r.stdout.slice(0, 400));

  // two files, oldest first: the first holds 10:00-10:10, the second 10:10-10:30
  const p1 = join(dir, 'page1.csv'), p2 = join(dir, 'page2.csv');
  writeFileSync(p1, csvOf(ROWS.slice(0, 3).map(([t, ...p]) => [t / 1000, ...p])));
  writeFileSync(p2, csvOf(ROWS.slice(2).map(([t, ...p]) => [t / 1000, ...p])));
  r = run(['score', '--calls', calls, '--bars', p1, '--bars', p2, '--json']);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout).calls, outs[0].calls);

  assert.match(run(['score', '--calls', calls, '--bars', csv, '--room', '0']).stderr, /--room must be above 0/);
  assert.match(run(['score', '--calls', calls, '--bars', csv, '--cost', 'free']).stderr, /--cost must be a dollar amount/);
  assert.match(run(['score', '--calls', calls, '--bars', csv, '--room', '1', '--room', '2']).stderr, /--room is given twice/);
  assert.match(run(['score', '--calls', join(dir, 'none.csv'), '--bars', csv]).stderr, /calls file .* not found/);
});
