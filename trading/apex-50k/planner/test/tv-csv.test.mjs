import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { readTvCsv, parseTvCsv, inspectTvCsv, parseNumber, parseTvDate, detectDelimiter, parseCsvRows, detectDateOrder } from '../tv-csv.mjs';
import { loadRules, makePaLedger, stepTrade, startDay, endDay } from '../ledger.mjs';
import { groupTradesByDay } from '../sim.mjs';

const fixtures = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg ?? ''} ${a} !== ${b}`);

test('parseNumber: minus signs, thousands separators, decimal commas, currency', () => {
  const cases = [
    ['150.00', 150],
    ['1,234.50', 1234.5],
    ['−325.00', -325],
    ['−1.250,50', -1250.5],
    ['2 010,00', 2010],
    ['2 010,00', 2010],
    ['2 010,00', 2010],
    ["1'234.5", 1234.5],
    ['1,234', 1234],
    ['0,50', 0.5],
    ['12,5', 12.5],
    ['1.234.567', 1234567],
    ['$1,000.25', 1000.25],
    ['-$45.10', -45.1],
    ['(75.00)', -75],
    ['120.00 USD', 120],
    ['+15', 15],
    ['', NaN],
    ['n/a', NaN],
  ];
  for (const [raw, want] of cases) {
    const got = parseNumber(raw);
    if (Number.isNaN(want)) assert.ok(Number.isNaN(got), `${raw} -> ${got}`);
    else near(got, want, raw);
  }
  near(parseNumber('1,234', ','), 1.234, 'explicit decimal comma');
});

test('delimiter detection and quoted fields', () => {
  assert.equal(detectDelimiter('a,b,c\n1;2'), ',');
  assert.equal(detectDelimiter('a;b;"x,y,z"\n'), ';');
  assert.equal(detectDelimiter('a\tb\tc'), '\t');
  assert.deepEqual(parseCsvRows('a;"b;c";"d ""q"""\r\n1;2;3\r\n\r\n', ';'), [
    ['a', 'b;c', 'd "q"'],
    ['1', '2', '3'],
  ]);
});

test('parseTvDate: formats and time zones', () => {
  assert.equal(parseTvDate('2024-03-15 09:31').toISOString(), '2024-03-15T13:31:00.000Z'); // EDT
  assert.equal(parseTvDate('2024-01-15 09:31').toISOString(), '2024-01-15T14:31:00.000Z'); // EST
  assert.equal(parseTvDate('2024-03-15 08:31', { tz: 'America/Chicago' }).toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('2024-03-15T13:31:00Z').toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('2024-03-15 14:31+01:00').toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('Mar 15, 2024, 09:31').toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('15.03.2024 09:31').toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('03/15/2024 9:31 AM').toISOString(), '2024-03-15T13:31:00.000Z');
  assert.equal(parseTvDate('garbage'), null);
});

test('parseTvDate: day-first month names use the chart time zone; the host time zone never matters', () => {
  const want = '2024-03-15T13:31:00.000Z';
  for (const s of ['15 Mar 2024 09:31', '15-Mar-2024 09:31', '15 March 2024 9:31 AM', 'Fri, 15 Mar 2024 09:31:00 -0400', 'Fri Mar 15 2024 09:31:00 GMT-0400']) {
    assert.equal(parseTvDate(s)?.toISOString(), want, s);
  }
  assert.equal(parseTvDate('2024 Mar 15 09:31'), null, 'unknown layout without an offset is not guessed');
  const code = `import(${JSON.stringify(new URL('../tv-csv.mjs', import.meta.url).href)}).then((m) => process.stdout.write(m.parseTvDate('15 Mar 2024 09:31').toISOString()))`;
  for (const TZ of ['Asia/Tokyo', 'America/Los_Angeles', 'UTC']) {
    const r = spawnSync(process.execPath, ['-e', code], { env: { ...process.env, TZ }, encoding: 'utf8' });
    assert.equal(r.stdout, want, `host TZ ${TZ}: ${r.stderr}`);
  }
});

test('date order is decided once per file', () => {
  const csv = (...dates) =>
    ['Trade #,Type,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD', ...dates.map((d, i) => `${i + 1},Exit long,${d},1,10,10,0`)].join('\n');
  // dd/mm file: 12/03 is 12 March because 13/03 shows the file is day-first.
  const dmy = inspectTvCsv(csv('12/03/2024 10:00', '13/03/2024 10:00'));
  assert.deepEqual(dmy.trades.map((t) => t.dayKey), ['2024-03-12', '2024-03-13']);
  assert.deepEqual(dmy.warnings, []);
  const mdy = inspectTvCsv(csv('03/12/2024 10:00', '03/13/2024 10:00'));
  assert.deepEqual(mdy.trades.map((t) => t.dayKey), ['2024-03-12', '2024-03-13']);
  // Ambiguous file: read as mm/dd with a warning, or as told.
  const amb = inspectTvCsv(csv('05/03/2024 10:00'));
  assert.equal(amb.trades[0].dayKey, '2024-05-03');
  assert.match(amb.fileWarnings[0], /ambiguous/);
  assert.equal(inspectTvCsv(csv('05/03/2024 10:00'), { dateOrder: 'dmy' }).trades[0].dayKey, '2024-03-05');
  // Contradictory file: an error, not a silent mix.
  assert.throws(() => inspectTvCsv(csv('13/03/2024 10:00', '03/14/2024 10:00')), /mix dd\/mm/);
  assert.deepEqual(detectDateOrder(['2024-03-05 10:00', '15.03.2024 09:00']), { order: 'mdy', ambiguous: false });
  assert.throws(() => inspectTvCsv(csv('05/03/2024 10:00'), { dateOrder: 'ymd' }), /unknown date order/);
});

test('old-format export: BOM, comma delimiter, Profit/Run-up/Drawdown/Contracts/Date/Time headers', () => {
  const meta = readTvCsv(join(fixtures, 'tv-old.csv'));
  assert.equal(meta.delimiter, ',');
  assert.deepEqual(meta.columns, {
    tradeNo: 'Trade #',
    type: 'Type',
    signal: 'Signal',
    time: 'Date/Time',
    contracts: 'Contracts',
    pnl: 'Profit USD',
    runUp: 'Run-up USD',
    drawdown: 'Drawdown USD',
  });
  assert.deepEqual(meta.warnings, []);
  const t = meta.trades;
  assert.deepEqual(t.map((x) => x.tradeNo), [1, 2, 3], 'sorted by exit time');
  assert.deepEqual(t.map((x) => x.dayKey), ['2024-03-15', '2024-03-15', '2024-03-18']);
  assert.equal(t[0].exitTime.toISOString(), '2024-03-15T14:12:00.000Z');
  assert.deepEqual(
    t.map(({ contracts, pnl, runUp, drawdown, pnlPer, mfePer, maePer, side }) => ({ contracts, pnl, runUp, drawdown, pnlPer, mfePer, maePer, side })),
    [
      { contracts: 1, pnl: 150, runUp: 210, drawdown: -35.5, pnlPer: 150, mfePer: 210, maePer: -35.5, side: 'long' },
      { contracts: 1, pnl: -325, runUp: 40, drawdown: -410, pnlPer: -325, mfePer: 40, maePer: -410, side: 'short' },
      { contracts: 2, pnl: 1234.5, runUp: 1410, drawdown: -120, pnlPer: 617.25, mfePer: 705, maePer: -60, side: 'long' },
    ],
  );
  for (const x of t) {
    assert.ok(x.mfePer >= 0);
    assert.ok(x.maePer <= 0);
  }
});

test("new-format export: ';' delimiter, Net P&L / excursion / Position size (qty) / Date and time headers", () => {
  const meta = readTvCsv(join(fixtures, 'tv-new.csv'));
  assert.equal(meta.delimiter, ';');
  assert.equal(meta.columns.pnl, 'Net P&L USD');
  assert.equal(meta.columns.runUp, 'Favorable excursion USD');
  assert.equal(meta.columns.drawdown, 'Adverse excursion USD');
  assert.equal(meta.columns.contracts, 'Position size (qty)', 'not the "(value)" column');
  assert.equal(meta.columns.time, 'Date and time');
  const t = meta.trades;
  assert.equal(t.length, 3);
  assert.deepEqual(t.map((x) => x.dayKey), ['2025-06-02', '2025-06-03', '2025-06-03']);
  assert.equal(t[0].exitTime.toISOString(), '2025-06-02T14:02:00.000Z');
  assert.equal(t[0].entryTime.toISOString(), '2025-06-02T13:31:00.000Z');
  near(t[0].pnl, 2010);
  assert.equal(t[0].contracts, 3);
  near(t[0].pnlPer, 670);
  near(t[0].mfePer, 800);
  near(t[0].maePer, -50);
  near(t[1].pnl, -1250.5);
  near(t[1].mfePer, 75);
  near(t[1].maePer, -1300, 'adverse excursion printed positive is normalized negative');
  assert.equal(t[1].side, 'short');
  near(t[2].pnlPer, -6);
  near(t[2].maePer, -24);
});

test('other header variants: P&L USD, Quantity, Date/time; time zone conversion to New York days', () => {
  const csv = [
    'Trade #,Type,Date/time,Quantity,P&L USD,Run-up USD,Drawdown USD',
    '1,Exit long,2024-01-02 23:30,4,"−1,000.00",200,"1,200.00"',
    '1,Entry long,2024-01-02 22:00,4,"−1,000.00",200,"1,200.00"',
    '2,Exit short,2024-01-03 10:00,4,400,500,−100',
  ].join('\n');
  const { trades, columns } = inspectTvCsv(csv, { tz: 'America/Chicago' });
  assert.equal(columns.time, 'Date/time');
  assert.equal(columns.contracts, 'Quantity');
  assert.equal(columns.pnl, 'P&L USD');
  assert.equal(trades[0].dayKey, '2024-01-03', '23:30 Chicago = 00:30 New York next day');
  near(trades[0].pnlPer, -250);
  near(trades[0].maePer, -300);
  near(trades[0].mfePer, 50);
  near(trades[1].pnlPer, 100);
  // Session roll: 23:30 Chicago is after 18:00 New York -> next session either way; 10:00 stays.
  const rolled = parseTvCsv(csv, { tz: 'America/Chicago', rollHour: 18 });
  assert.deepEqual(rolled.map((x) => x.dayKey), ['2024-01-03', '2024-01-03']);
});

test('trades exiting after 18:00 ET belong to the next Apex session by default (DLL and qualifying days)', () => {
  const rules = loadRules();
  const csv = (a, b) =>
    [
      'Trade #,Type,Signal,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD',
      `2,Exit Long,X,2024-03-19 10:30,1,${b},${Math.max(b, 0)},${Math.max(-b, 0)}`,
      '2,Entry Long,L,2024-03-19 10:00,1,0,0,0',
      `1,Exit Long,X,2024-03-18 19:30,1,${a},${Math.max(a, 0)},${Math.max(-a, 0)}`,
      '1,Entry Long,L,2024-03-18 19:00,1,0,0,0',
    ].join('\n');
  const runPa = (trades) => {
    const P = makePaLedger(rules);
    for (const d of groupTradesByDay(trades)) {
      startDay(P, d.dayKey);
      for (const t of d.trades) stepTrade(P, { favorable: t.mfePer, adverse: t.maePer, close: t.pnlPer });
      endDay(P);
    }
    return P;
  };
  // Monday 19:30 ET is in Tuesday's session (Globex opens 18:00 ET), as the Pine's time_tradingday counts it.
  const losses = csv(-800, -300);
  assert.deepEqual(parseTvCsv(losses).map((t) => t.dayKey), ['2024-03-19', '2024-03-19']);
  assert.deepEqual(parseTvCsv(losses, { rollHour: null }).map((t) => t.dayKey), ['2024-03-18', '2024-03-19'], 'opt-out: calendar date');
  assert.equal(runPa(parseTvCsv(losses)).dllHits, 1, 'one session at -1,100 hits the 1,000 DLL');
  assert.equal(runPa(parseTvCsv(losses, { rollHour: null })).dllHits, 0);
  const gains = csv(150, 100);
  assert.equal(runPa(parseTvCsv(gains)).qualDays, 1, 'one $250 session qualifies');
  assert.equal(runPa(parseTvCsv(gains, { rollHour: null })).qualDays, 0);
});

test('missing optional columns: file warnings, 1 contract, excursions fall back to the close', () => {
  const csv = ['Trade #,Type,Signal,Date/Time,Profit USD', '1,Exit Long,SL,2024-03-19 10:30,-600', '1,Entry Long,L,2024-03-19 10:00,-600', '2,Exit Long,TP,2024-03-19 11:30,500'].join('\n');
  const { trades, warnings, fileWarnings } = inspectTvCsv(csv);
  assert.equal(fileWarnings.length, 2);
  assert.match(fileWarnings[0], /no contracts column/);
  assert.match(fileWarnings[1], /no Run-up\/Drawdown column/);
  assert.deepEqual(warnings, fileWarnings);
  assert.deepEqual(
    trades.map((t) => [t.contracts, t.pnlPer, t.mfePer, t.maePer]),
    [
      [1, -600, 0, -600],
      [1, 500, 500, 0],
    ],
  );
  // A recorded excursion smaller than the close is widened to the close.
  const odd = inspectTvCsv('Trade #,Type,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD\n1,Exit long,2024-03-19 10:30,2,-300,40,100\n');
  assert.deepEqual(odd.fileWarnings, []);
  assert.deepEqual([odd.trades[0].mfePer, odd.trades[0].maePer], [20, -150]);
});

test('a trade with an Entry row but no Exit row is skipped, not booked at its entry', () => {
  const csv = [
    'Trade #,Type,Signal,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD',
    '2,Entry Long,Long,2024-03-18 15:41,10,"-1,500.00",10,"1,600.00"',
    '1,Exit Long,TP,2024-03-18 11:00,1,50,60,5',
    '1,Entry Long,Long,2024-03-18 10:00,1,50,60,5',
  ].join('\n');
  const { trades, warnings } = inspectTvCsv(csv);
  assert.deepEqual(trades.map((t) => t.tradeNo), [1]);
  assert.match(warnings[0], /trade 2: no exit row/);
  // A Type column that never names an exit (other language) falls back to the latest row.
  const other = inspectTvCsv('Trade #,Type,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD\n1,Sortie,2024-03-18 11:00,1,50,60,5\n1,Achat,2024-03-18 10:00,1,50,60,5\n');
  assert.equal(other.trades.length, 1);
  assert.equal(other.trades[0].exitTime.toISOString(), '2024-03-18T15:00:00.000Z');
  assert.match(other.fileWarnings[0], /no Exit rows/);
});

test('no Type column: exit is the latest row of each trade; open trades are skipped', () => {
  const csv = [
    'Trade #,Signal,Date/Time,Contracts,Profit USD,Run-up USD,Drawdown USD',
    '2,Open,2024-01-05 15:59,1,80,90,10',
    '2,Long,2024-01-05 15:00,1,80,90,10',
    '1,TP,2024-01-04 11:00,1,50,60,5',
    '1,Long,2024-01-04 10:00,1,50,60,5',
  ].join('\n');
  const { trades, warnings } = inspectTvCsv(csv);
  assert.equal(trades.length, 1);
  assert.equal(trades[0].exitTime.toISOString(), '2024-01-04T16:00:00.000Z');
  assert.equal(trades[0].entryTime.toISOString(), '2024-01-04T15:00:00.000Z');
  assert.match(warnings[0], /still open/);
  assert.equal(parseTvCsv(csv, { includeOpen: true }).length, 2);
});

test('missing required columns is a clear error', () => {
  assert.throws(() => parseTvCsv('Trade #,Type,Price\n1,Exit long,5\n'), /missing required column/);
});
