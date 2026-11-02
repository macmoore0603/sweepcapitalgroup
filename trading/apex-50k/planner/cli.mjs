#!/usr/bin/env node
// cli.mjs - Apex 50K Intraday planner: odds of passing the evaluation and then reaching payouts, by size.
// Run `node planner/cli.mjs --help` for usage. Dependency-free (node: built-ins only).

import { resolve, basename } from 'node:path';
import { pathToFileURL } from 'node:url';
import {
  loadRules,
  RULES_PATH,
  evalStopLevel,
  paStopLevel,
  normalizeFeed,
  normalizeOrder,
  normalizeUnit,
  normalizeDllFill,
} from './ledger.mjs';
import { readTvCsv } from './tv-csv.mjs';
import { NY, SESSION_ROLL_HOUR } from './time.mjs';
import {
  makeParametricSource,
  makeEmpiricalSource,
  zeroEdgeWinRate,
  sweep,
  replayEval,
  evalSessionBudgets,
  PARAMETRIC_DEFAULTS,
} from './sim.mjs';

class UsageError extends Error {}

const VALUED = new Set([
  'trades', 'extra-cost', 'tz', 'session-roll', 'date-order', 'decimal',
  'win', 'rr', 'loss-r', 'risk', 'tpd', 'cost', 'mfe-losers', 'mae-winners', 'r-spread',
  'contracts', 'unit', 'mode', 'feed', 'order', 'dll-fill', 'attempts', 'pa-runs', 'days', 'horizon', 'fee', 'seed', 'rules',
]);
const FLAGS = new Set(['sweep', 'json', 'help', 'zero-edge']);
/** CLI default for --r-spread: real stops vary in width, so a fixed size does not risk exactly 1R per trade. */
export const CLI_R_SPREAD = 0.5;

export function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '-h') {
      out.help = true;
      continue;
    }
    if (!a.startsWith('--')) throw new UsageError(`unexpected argument "${a}"`);
    let key = a.slice(2);
    let val;
    const eq = key.indexOf('=');
    if (eq >= 0) {
      val = key.slice(eq + 1);
      key = key.slice(0, eq);
    }
    if (FLAGS.has(key)) {
      out[key] = val === undefined ? true : !/^(false|0|no)$/i.test(val);
      continue;
    }
    if (!VALUED.has(key)) throw new UsageError(`unknown option --${key}`);
    if (val === undefined) {
      val = argv[++i];
      if (val === undefined) throw new UsageError(`--${key} needs a value`);
    }
    out[key] = val;
  }
  return out;
}

/** Run fn, reporting option-validation errors (e.g. an unknown --feed) as usage errors. */
function asUsage(fn) {
  try {
    return fn();
  } catch (err) {
    if (err instanceof UsageError) throw err;
    throw new UsageError(err.message);
  }
}

function number(args, key, { def, min = -Infinity, max = Infinity, int = false, gt = false } = {}) {
  if (args[key] == null) return def;
  const v = Number(String(args[key]).replace(/[$,_]/g, ''));
  const okMin = gt ? v > min : v >= min;
  if (!Number.isFinite(v) || !okMin || v > max || (int && !Number.isInteger(v))) {
    const range = `${gt ? '>' : '>='} ${min}${max < Infinity ? ` and <= ${max}` : ''}`;
    throw new UsageError(`--${key} must be ${int ? 'an integer' : 'a number'} ${range}, got "${args[key]}"`);
  }
  return v;
}

/** "3" | "1..4" | "2..60:2" | "1,2,4" -> sorted unique sizes */
export function parseSizes(spec, cap) {
  const out = new Set();
  for (const part of String(spec).split(',')) {
    const p = part.trim();
    const m = /^(\d+)\s*\.\.\s*(\d+)(?:\s*:\s*(\d+))?$/.exec(p);
    if (m) {
      const [a, b, step] = [+m[1], +m[2], +(m[3] ?? 1)];
      if (step < 1 || a > b) throw new UsageError(`bad --contracts range "${p}"`);
      for (let q = a; q <= b; q += step) out.add(q);
    } else if (/^\d+$/.test(p)) out.add(+p);
    else throw new UsageError(`bad --contracts value "${p}" (use N, A..B, A..B:step or A,B,C)`);
  }
  const sizes = [...out].sort((x, y) => x - y);
  for (const q of sizes) {
    if (q < 1 || q > cap) throw new UsageError(`--contracts ${q} is outside 1..${cap} (evaluation cap for this unit)`);
  }
  return sizes;
}

// ---------------------------------------------------------------------------------------------- formatting

const isNum = (x) => typeof x === 'number' && !Number.isNaN(x);
const pct = (x, d = 1) => (isNum(x) ? `${(100 * x).toFixed(d)}%` : '-');
function usd(x, d = 0) {
  if (!isNum(x)) return '-';
  if (!Number.isFinite(x)) return 'never';
  const s = Math.abs(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  return `${x < 0 && Math.abs(x) >= 0.5 * 10 ** -d ? '-' : ''}$${s}`;
}
const fx = (x, d = 1) => (isNum(x) ? (Number.isFinite(x) ? x.toFixed(d) : 'never') : '-');
const int = (x) => (isNum(x) ? Math.round(x).toLocaleString('en-US') : '-');

function table(headers, rows, leftCols = new Set()) {
  const w = headers.map((h, i) => Math.max(h.length, ...rows.map((r) => String(r[i]).length)));
  const line = (cells) =>
    cells
      .map((c, i) => (leftCols.has(i) ? String(c).padEnd(w[i]) : String(c).padStart(w[i])))
      .join('  ')
      .replace(/\s+$/, '');
  const rule = line(w.map((n, i) => (headers[i] === '' ? '' : '-'.repeat(n))));
  return [line(headers), rule, ...rows.map(line)].join('\n');
}

function jsonReplacer(_k, v) {
  if (typeof v === 'number' && !Number.isFinite(v)) return null;
  return v;
}

// ---------------------------------------------------------------------------------------------- main

function usage(rules) {
  const e = rules?.evaluation;
  const stop = e?.thresholdStopRithmic != null ? `stops trailing at $${e.thresholdStopRithmic.toLocaleString('en-US')}` : 'keeps trailing';
  const cap = e ? `${e.maxContractsMini} minis / ${e.maxContractsMini * rules.microsPerMini} micros` : 'evaluation cap';
  return `Apex 50K Intraday planner - odds of passing the evaluation and reaching payouts, by size.

Usage:
  node planner/cli.mjs (--trades list.csv | --win 0.45 --rr 2 --risk 100 [--tpd 2] [--cost 1.34])
                       [--contracts N | --contracts A..B | --sweep] [--mode eval|pa|both]
                       [--feed rithmic|tradovate] [--order conservative|adverse-first]
                       [--attempts 20000] [--days N] [--horizon 120] [--fee 0] [--seed 1] [--json]

Trade source (one of):
  --trades FILE         TradingView Strategy Tester "List of trades" CSV; whole trading sessions are
                        bootstrapped, including the sessions between the first and last trade with no
                        trades (real trades per session and their order are kept)
    --extra-cost $      extra round-trip cost per contract on top of the CSV P&L (default 0; TradingView
                        P&L already includes the strategy's commission)
    --tz ZONE           time zone of the CSV timestamps (chart time zone; default ${NY})
    --session-roll H|off   exits at/after H:00 New York time count toward the next day's session
                        (default ${SESSION_ROLL_HOUR}, the Apex / CME Globex roll; off = calendar date)
    --date-order auto|mdy|dmy   order of numeric dates such as 05/03/2024 (default auto: one order for
                        the whole file, from any value above 12)
    --decimal auto|.|,  decimal separator of the numbers (default auto)
  --win P               parametric win rate, 0..1
  --rr R                average win in R
  --risk $              dollars at risk per contract for 1R
  --tpd N               trades per day (default ${PARAMETRIC_DEFAULTS.tradesPerDay}; fractions allowed)
  --cost $              round-trip cost per contract (default ${PARAMETRIC_DEFAULTS.costPerContract})
  --loss-r R            average loss in R (default ${PARAMETRIC_DEFAULTS.avgLossR})
  --mfe-losers R        how far losers first run in favor, in R (default ${PARAMETRIC_DEFAULTS.mfeOnLosersR})
  --mae-winners R       how far winners first dip, in R (default ${PARAMETRIC_DEFAULTS.maeOnWinnersR})
  --r-spread S          each trade's 1R varies uniformly by +-S (mean unchanged), like stops of different
                        widths at one size; 0 = every trade exactly +-R (default ${CLI_R_SPREAD})
  --zero-edge           replace --win with the win rate that makes expectancy before costs exactly 0

Size and run:
  --contracts SPEC      N, A..B, A..B:step or A,B,C (default: --sweep)
  --sweep               every size from 1 to the evaluation cap (${cap})
  --unit mini|micro     contract unit (default mini)
  --mode eval|pa|both   evaluation, performance account after a pass, or both (default both)
  --feed rithmic|tradovate   evaluation feed; Rithmic/WealthCharts threshold ${stop} (default rithmic)
  --order conservative|adverse-first   intratrade order (default conservative: favorable extreme first)
  --dll-fill extreme|limit   PA daily-loss flatten at the trade's adverse extreme (default, conservative)
                        or exactly at the limit (platform liquidation; can keep a breach from happening)
  --attempts N          evaluation attempts per size (default 20000)
  --pa-runs N           performance-account runs per size (default: same as --attempts)
  --days N              trading sessions per evaluation attempt (default: the Monday-Friday sessions in
                        the ${e?.accessDays ?? 30}-calendar-day access, ${budgetLabel(rules ? evalSessionBudgets(rules) : null)}, by start weekday)
  --horizon N           PA trading days simulated after a pass (default 120)
  --fee $               evaluation fee per attempt (default 0)
  --seed N              PRNG seed (default 1)
  --rules FILE          rules file (default ${RULES_PATH})
  --json                machine-readable output
  --help                this text
`;
}

/** "21" or "21-22" for a list of per-attempt session budgets. */
function budgetLabel(budgets) {
  if (!budgets || budgets.length === 0) return '21-22';
  const lo = Math.min(...budgets);
  const hi = Math.max(...budgets);
  return lo === hi ? `${lo}` : `${lo}-${hi}`;
}

function buildSource(args, rules) {
  const parametricKeys = ['win', 'rr', 'risk', 'tpd', 'cost', 'loss-r', 'mfe-losers', 'mae-winners', 'r-spread', 'zero-edge'];
  if (args.trades) {
    const clash = parametricKeys.filter((k) => args[k] != null);
    if (clash.length) throw new UsageError(`--trades cannot be combined with ${clash.map((k) => `--${k}`).join(', ')}`);
    const path = resolve(args.trades);
    const rollOff = args['session-roll'] != null && /^(off|none|no|false)$/i.test(String(args['session-roll']));
    const rollHour = rollOff ? null : number(args, 'session-roll', { def: SESSION_ROLL_HOUR, min: 0, max: 23, int: true });
    const dateOrder = String(args['date-order'] ?? 'auto').toLowerCase();
    if (!['auto', 'mdy', 'dmy'].includes(dateOrder)) throw new UsageError(`--date-order must be auto, mdy or dmy, got "${args['date-order']}"`);
    const decimal = String(args.decimal ?? 'auto').toLowerCase();
    if (!['auto', '.', ','].includes(decimal)) throw new UsageError(`--decimal must be auto, . or ',', got "${args.decimal}"`);
    const meta = readTvCsv(path, { tz: args.tz ?? NY, rollHour, dateOrder, decimal });
    if (meta.trades.length === 0) throw new UsageError(`no trades could be read from ${path}`);
    const extraCost = number(args, 'extra-cost', { def: 0, min: 0 });
    const source = makeEmpiricalSource(meta.trades, { extraCost });
    return {
      source,
      trades: meta.trades,
      info: {
        kind: 'empirical',
        file: path,
        trades: source.trades,
        days: source.days,
        sessions: source.sessions,
        activeShare: source.activeShare,
        firstDay: source.firstDay,
        lastDay: source.lastDay,
        tradesPerDay: source.tradesPerDay,
        tradesPerActiveDay: source.tradesPerActiveDay,
        sessionRoll: rollHour,
        winRate: source.winRate,
        extraCost,
        expectancyPerContract: source.expectancyPerContract,
        columns: meta.columns,
        delimiter: meta.delimiter,
        warnings: meta.warnings,
        fileWarnings: meta.fileWarnings,
      },
    };
  }
  for (const k of ['extra-cost', 'tz', 'session-roll', 'date-order', 'decimal']) {
    if (args[k] != null) throw new UsageError(`--${k} only applies with --trades`);
  }
  const missing = ['rr', 'risk', ...(args['zero-edge'] ? [] : ['win'])].filter((k) => args[k] == null);
  if (missing.length) {
    throw new UsageError(`give --trades FILE or a parametric distribution (missing ${missing.map((k) => `--${k}`).join(', ')})`);
  }
  const avgWinR = number(args, 'rr', { min: 0, gt: true });
  const avgLossR = number(args, 'loss-r', { def: PARAMETRIC_DEFAULTS.avgLossR, min: 0, gt: true });
  const params = {
    winRate: args['zero-edge'] ? zeroEdgeWinRate(avgWinR, avgLossR) : number(args, 'win', { min: 0, max: 1 }),
    avgWinR,
    avgLossR,
    riskPerContract: number(args, 'risk', { min: 0, gt: true }),
    tradesPerDay: number(args, 'tpd', { def: PARAMETRIC_DEFAULTS.tradesPerDay, min: 0, gt: true }),
    costPerContract: number(args, 'cost', { def: PARAMETRIC_DEFAULTS.costPerContract, min: 0 }),
    mfeOnLosersR: number(args, 'mfe-losers', { def: PARAMETRIC_DEFAULTS.mfeOnLosersR, min: 0 }),
    maeOnWinnersR: number(args, 'mae-winners', { def: PARAMETRIC_DEFAULTS.maeOnWinnersR, min: 0 }),
    rSpread: number(args, 'r-spread', { def: CLI_R_SPREAD, min: 0, max: 0.95 }),
  };
  const source = makeParametricSource(params);
  return {
    source,
    trades: null,
    info: {
      kind: 'parametric',
      zeroEdge: Boolean(args['zero-edge']),
      ...source.params,
      expectancyBeforeCosts: source.expectancyBeforeCosts,
      expectancyPerContract: source.expectancyPerContract,
    },
  };
}

export function run(argv) {
  const args = parseArgs(argv);
  let rules = null;
  try {
    rules = loadRules(args.rules ? resolve(args.rules) : RULES_PATH);
  } catch (err) {
    if (!args.help) throw err;
  }
  if (args.help) return { text: usage(rules) };

  const { source, trades, info } = buildSource(args, rules);
  const unit = asUsage(() => normalizeUnit(args.unit ?? 'mini'));
  const mode = String(args.mode ?? 'both').toLowerCase();
  if (!['eval', 'pa', 'both'].includes(mode)) throw new UsageError(`--mode must be eval, pa or both, got "${args.mode}"`);
  const evalCap = rules.evaluation.maxContractsMini * (unit === 'micro' ? rules.microsPerMini : 1);
  if (args.sweep && args.contracts != null) throw new UsageError('use --contracts or --sweep, not both');
  const sizes = args.contracts != null ? parseSizes(args.contracts, evalCap) : Array.from({ length: evalCap }, (_, i) => i + 1);
  const attempts = number(args, 'attempts', { def: 20000, min: 1, int: true });
  const settings = asUsage(() => ({
    mode,
    unit,
    feed: normalizeFeed(args.feed ?? 'rithmic'),
    order: normalizeOrder(args.order ?? 'conservative'),
    dllFill: normalizeDllFill(args['dll-fill'] ?? 'extreme'),
    attempts,
    paRuns: number(args, 'pa-runs', { def: attempts, min: 1, int: true }),
    tradingDays: number(args, 'days', { def: null, min: 1, int: true }), // null: derived from rules.json accessDays
    horizonDays: number(args, 'horizon', { def: 120, min: 1, int: true }),
    fee: number(args, 'fee', { def: 0, min: 0 }),
    seed: number(args, 'seed', { def: 1, min: 0, max: 4294967295, int: true }),
  }));

  const res = sweep(rules, source, { ...settings, sizes });
  const replay =
    trades && mode !== 'pa'
      ? sizes.map((q) => {
          const r = replayEval(rules, trades, { contracts: q, feed: settings.feed, order: settings.order, unit, extraCost: info.extraCost });
          delete r.attempts; // per-attempt detail is long; the summary counts are what the table shows
          return r;
        })
      : null;

  const out = {
    planner: 'apex-50k',
    rules: { file: args.rules ? resolve(args.rules) : RULES_PATH, firm: rules.firm, plan: rules.plan, verifiedOn: rules.verifiedOn },
    source: info,
    settings: {
      ...settings,
      sizes,
      evalCap,
      evalSessionBudgets: evalSessionBudgets(rules, settings.tradingDays),
      evalThresholdStop: evalStopLevel(rules, settings.feed),
      paThresholdStop: paStopLevel(rules),
    },
    results: res.results,
    best: res.best,
    replay,
  };
  out.summary = summaryLine(out);
  if (args.json) return { text: JSON.stringify(out, jsonReplacer, 2), data: out };
  return { text: renderText(out, rules), data: out };
}

function describeSource(s, unitName) {
  if (s.kind === 'empirical') {
    const rowWarnings = s.warnings.length - (s.fileWarnings?.length ?? 0);
    const roll = s.sessionRoll == null ? 'calendar days' : `sessions roll at ${s.sessionRoll}:00 ET`;
    return [
      `TradingView CSV ${basename(s.file)}: ${int(s.trades)} trades on ${int(s.days)} of ${int(s.sessions)} sessions ` +
        `(${pct(s.activeShare)} active; ${s.firstDay}..${s.lastDay}), ${fx(s.tradesPerDay, 2)} trades/session ` +
        `(${fx(s.tradesPerActiveDay, 2)} per active session), win ${pct(s.winRate)}`,
      `expectancy ${usd(s.expectancyPerContract, 2)} per trade per ${unitName} after ${usd(s.extraCost, 2)} extra cost; ` +
        `whole sessions bootstrapped (${roll})${rowWarnings > 0 ? `; ${rowWarnings} row warning(s)` : ''}`,
      ...(s.fileWarnings ?? []).map((w) => `WARNING: ${w}`),
    ];
  }
  return [
    `parametric${s.zeroEdge ? ' (zero-edge win rate)' : ''}: win ${pct(s.winRate)}, avg win ${fx(s.avgWinR, 2)}R / avg loss ` +
      `${fx(s.avgLossR, 2)}R, 1R = ${usd(s.riskPerContract)} per ${unitName}, ${fx(s.tradesPerDay, 2)} trades/day, ` +
      `cost ${usd(s.costPerContract, 2)} per ${unitName} round trip`,
    `winners first dip ${fx(s.maeOnWinnersR, 2)}R, losers first run ${fx(s.mfeOnLosersR, 2)}R; ` +
      `1R per trade ${s.rSpread > 0 ? `varies +-${pct(s.rSpread, 0)}` : 'fixed'}; expectancy ` +
      `${usd(s.expectancyPerContract, 2)} per trade per ${unitName} after costs`,
  ];
}

function renderText(out, rules) {
  const s = out.settings;
  const e = rules.evaluation;
  const pa = rules.performanceAccount;
  const unitName = s.unit === 'micro' ? 'micro' : 'mini';
  const stop = Number.isFinite(s.evalThresholdStop) ? `stops at ${usd(s.evalThresholdStop)}` : 'never stops';
  const lines = [];
  const src = describeSource(out.source, unitName);
  lines.push(`Apex 50K Intraday planner - ${rules.firm} ${rules.plan} (rules verified ${rules.verifiedOn})`);
  lines.push(`Trades : ${src[0]}`);
  for (const l of src.slice(1)) lines.push(`         ${l}`);
  lines.push(
    `Rules  : eval target +${usd(e.profitTarget)}, trailing drawdown ${usd(e.maxDrawdown)} (${s.feed}: threshold ${stop}), ` +
      `max ${e.maxContractsMini} minis, ${e.accessDays}-day access`,
  );
  lines.push(
    `         PA drawdown ${usd(pa.maxDrawdown)} (stops at ${usd(s.paThresholdStop)}), ${pa.tiers.length} tiers from prior close, ` +
      `DLL pauses the session, up to ${pa.payout.maxPayouts} payouts`,
  );
  const runBits = [];
  if (s.mode !== 'pa') {
    const days = s.tradingDays != null ? `${s.tradingDays} sessions` : `${budgetLabel(s.evalSessionBudgets)} sessions (${e.accessDays} calendar days)`;
    runBits.push(`${int(s.attempts)} attempts x ${days}`);
  }
  if (s.mode !== 'eval') runBits.push(`${int(s.paRuns)} PA runs x ${s.horizonDays} trading days`);
  const dllBit = s.mode !== 'eval' ? `; DLL fill ${s.dllFill}` : '';
  lines.push(`Run    : ${runBits.join(', ')}; order ${s.order}${dllBit}; unit ${unitName}; fee ${usd(s.fee)}; seed ${s.seed}`);

  const bestPass = out.best.pass?.contracts;
  const bestPay = out.best.payoutPerFee?.contracts;
  if (s.mode !== 'pa') {
    lines.push('', 'EVALUATION (share of attempts)');
    const rows = out.results.map((r) => {
      const v = r.eval;
      return [
        r.contracts,
        pct(v.pPass),
        pct(v.pBreach),
        pct(v.pExpire),
        v.medianDaysToPass == null ? '-' : `${v.medianDaysToPass}/${v.p90DaysToPass}`,
        fx(v.attemptsPerPass, 1),
        s.fee > 0 ? usd(v.feesPerPass) : '-',
        r.contracts === bestPass ? '<- best P(pass)' : '',
      ];
    });
    lines.push(
      table(['Qty', 'P(pass)', 'P(breach)', 'P(expire)', 'Days to pass med/p90', 'Attempts/pass', 'Fees/pass', ''], rows, new Set([7])),
    );
  }
  if (s.mode !== 'eval') {
    lines.push('', `PERFORMANCE ACCOUNT after a pass (${s.horizonDays} trading days; per funded account unless noted)`);
    const rows = out.results.map((r) => {
      const v = r.pa;
      const c = r.combined;
      return [
        r.contracts,
        pct(v.pPayout),
        `${fx(v.meanPayouts, 2)}/${v.medianPayouts}`,
        `${usd(v.meanPaid)}/${usd(v.medianPaid)}`,
        pct(v.pBreachBeforeFirstPayout),
        c ? pct(c.pPassAndPayout) : '-',
        c ? usd(c.expectedPaidPerAttempt) : '-',
        c && c.paidPerFee != null ? fx(c.paidPerFee, 2) : '-',
        r.contracts === bestPay ? (s.mode === 'both' ? '<- best payout/fee' : '<- best payout') : '',
      ];
    });
    lines.push(
      table(
        ['Qty', 'P(1+ payout)', 'Payouts mean/med', 'Paid mean/med', 'P(breach<1st pay)', 'P(pass+payout)*', 'Paid/attempt*', 'Paid/$1 fee*', ''],
        rows,
        new Set([8]),
      ),
    );
    if (s.mode === 'both') lines.push('* per evaluation attempt: P(pass) x PA result');
  }
  if (out.replay) {
    lines.push(
      '',
      `HISTORICAL REPLAY (actual trade order; each attempt starts at the session after the previous one ends; ${e.accessDays}-calendar-day expiry)`,
    );
    const rows = out.replay.map((r) => [r.contracts, r.total, r.passed, r.breached, r.expired, r.open, pct(r.passRate)]);
    lines.push(table(['Qty', 'Attempts', 'Passed', 'Breached', 'Expired', 'Open', 'Pass rate'], rows));
  }
  lines.push('', out.summary);
  return lines.join('\n');
}

function summaryLine(out) {
  const s = out.settings;
  const b = out.best;
  const parts = [];
  const plural = (q) => `${q} ${s.unit === 'micro' ? 'micro' : 'mini'}${q === 1 ? '' : 's'}`;
  const find = (q) => out.results.find((r) => r.contracts === q);
  if (s.mode !== 'pa') {
    if (b.pass) {
      const r = find(b.pass.contracts).eval;
      parts.push(
        `${plural(b.pass.contracts)} gives the best chance of passing (${pct(r.pPass)}, about 1 pass per ${fx(r.attemptsPerPass, 1)} attempts` +
          `${r.medianDaysToPass != null ? `, median ${r.medianDaysToPass} trading days` : ''})`,
      );
    } else parts.push(`no size passed in ${int(s.attempts)} attempts`);
  }
  if (s.mode === 'both') {
    if (b.payoutPerFee) {
      const r = find(b.payoutPerFee.contracts);
      const perFee = s.fee > 0 ? `, ${fx(r.combined.paidPerFee, 2)} per $1 of fees` : '; no --fee given, so ranked by $ paid per attempt';
      parts.push(
        `${plural(b.payoutPerFee.contracts)} gives the most expected payout per evaluation fee (${usd(r.combined.expectedPaidPerAttempt)} paid per attempt${perFee}), and ` +
          `${pct(r.combined.pPassAndPayout)} of attempts at that size pass and then collect a payout within ${s.horizonDays} trading days`,
      );
    } else parts.push(`no size reached a payout within ${s.horizonDays} trading days`);
  } else if (s.mode === 'pa') {
    if (b.payoutPerFee) {
      const r = find(b.payoutPerFee.contracts).pa;
      parts.push(
        `in a funded account ${plural(b.payoutPerFee.contracts)} pays the most (${usd(r.meanPaid)} on average within ${s.horizonDays} trading days; ` +
          `${pct(r.pPayout)} reach at least one payout)`,
      );
    } else parts.push(`no size reached a payout within ${s.horizonDays} trading days`);
  }
  let text = `Summary: ${parts.join('; ')}.`;
  const ex = out.source.expectancyPerContract;
  if (Math.abs(ex) < 1e-9) text += ' Expectancy after costs is zero, so these odds come from variance alone.';
  else if (ex < 0) text += ` Expectancy after costs is negative (${usd(ex, 2)} per trade per contract): passes here are luck, not edge.`;
  return text;
}

function isMain() {
  try {
    return import.meta.url === pathToFileURL(process.argv[1] ?? '').href;
  } catch {
    return false;
  }
}

if (isMain()) {
  try {
    const { text } = run(process.argv.slice(2));
    process.stdout.write(`${text}\n`);
  } catch (err) {
    if (err instanceof UsageError) {
      process.stderr.write(`error: ${err.message}\nRun with --help for usage.\n`);
      process.exitCode = 2;
    } else {
      process.stderr.write(`error: ${err.message}\n`);
      process.exitCode = 1;
    }
  }
}
