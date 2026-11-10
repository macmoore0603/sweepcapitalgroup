#!/usr/bin/env node
// cli.mjs - Apex 50K Intraday planner: odds of passing the evaluation and then reaching payouts, by size.
// With --firm tradeify: Tradeify 50K funded-account payouts and breach odds, by size (tradeify.mjs).
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
import { readTvCsv, mergeLegs } from './tv-csv.mjs';
import { NY, SESSION_ROLL_HOUR, addDays } from './time.mjs';
import {
  makeParametricSource,
  makeEmpiricalSource,
  defaultSizes,
  zeroEdgeWinRate,
  sweep,
  replayEval,
  evalSessionBudgets,
  PARAMETRIC_DEFAULTS,
} from './sim.mjs';
import {
  TRADEIFY_RULES_PATH,
  PLAN_KEYS,
  loadTradeifyRules,
  resolvePlan,
  normalizePlan,
  normalizePayoutPolicy,
  planCap,
  sessionRollHour,
  simulateFunded,
  replayFunded,
  flatTimeViolations,
  microscalpingCheck,
  resolveStartState,
  makeFundedLedger,
  payoutCheck,
  payoutBlockers,
} from './tradeify.mjs';

class UsageError extends Error {}

const VALUED = new Set([
  'trades', 'extra-cost', 'tz', 'session-roll', 'date-order', 'decimal',
  'win', 'rr', 'loss-r', 'risk', 'tpd', 'cost', 'mfe-losers', 'mae-winners', 'r-spread',
  'contracts', 'scale', 'unit', 'mode', 'feed', 'order', 'dll-fill', 'attempts', 'pa-runs', 'days', 'horizon', 'fee', 'seed', 'rules',
  'firm', 'plan', 'payout', 'runs', 'early-close', 'from', 'to',
  'balance', 'floor', 'high-eod', 'cycle-start', 'qual-days', 'cycle-max-day', 'payouts-taken',
]);
const FLAGS = new Set(['sweep', 'json', 'help', 'zero-edge', 'legacy', 'select-caps-before-2026-09-01', 'no-merge-legs']);
/** Tradeify start-state options: start from the account held now instead of a fresh one. */
export const START_OPTIONS = Object.freeze(['balance', 'floor', 'high-eod', 'cycle-start', 'qual-days', 'cycle-max-day', 'payouts-taken']);
/** Options that only apply with --firm tradeify, and Apex evaluation / PA options that do not apply there. */
const TRADEIFY_ONLY = ['plan', 'legacy', 'select-caps-before-2026-09-01', 'payout', 'runs', 'early-close', ...START_OPTIONS];
const APEX_ONLY = ['feed', 'attempts', 'pa-runs', 'days', 'fee'];
export const FIRMS = Object.freeze(['apex', 'tradeify']);
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

/** Warn (in the source's file warnings) when trades exceed the plan cap as traded, e.g. a micro export read as minis. */
function noteOverCap(info, trades, cap, unit, capName) {
  const over = trades.filter((t) => t.contracts > cap).length;
  if (!over) return;
  info.fileWarnings = [
    ...(info.fileWarnings ?? []),
    `${over} of ${trades.length} trades exceed ${capName} (${cap} ${unit}s) as traded, so they are capped even at 1x; check --unit (a micro export needs --unit micro)`,
  ];
  info.warnings = [...(info.warnings ?? []), info.fileWarnings[info.fileWarnings.length - 1]];
}

/** "3" | "1..4" | "2..60:2" | "1,2,4" -> sorted unique sizes */
export function parseSizes(spec, cap, capLabel = 'evaluation cap for this unit') {
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
    if (q < 1 || q > cap) throw new UsageError(`--contracts ${q} is outside 1..${cap} (${capLabel})`);
  }
  return sizes;
}

/** "2024-11-29,2024-12-24" -> sorted unique valid YYYY-MM-DD days */
function parseDayList(spec, opt) {
  const days = String(spec)
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
  if (days.length === 0) throw new UsageError(`${opt} needs one or more dates YYYY-MM-DD,YYYY-MM-DD,...`);
  for (const d of days) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || addDays(d, 0) !== d) throw new UsageError(`${opt}: bad date "${d}" (expected YYYY-MM-DD)`);
  }
  return [...new Set(days)].sort();
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

function usage(rules, tradeify = null) {
  const e = rules?.evaluation;
  const stop = e?.thresholdStopRithmic != null ? `stops trailing at $${e.thresholdStopRithmic.toLocaleString('en-US')}` : 'keeps trailing';
  const cap = e ? `${e.maxContractsMini} minis / ${e.maxContractsMini * rules.microsPerMini} micros` : 'evaluation cap';
  return `Apex 50K Intraday planner - odds of passing the evaluation and reaching payouts, by size.

Usage:
  node planner/cli.mjs (--trades list.csv | --win 0.45 --rr 2 --risk 100 [--tpd 2] [--cost 1.34])
                       [--contracts N | --contracts A..B | --sweep] [--mode eval|pa|both]
                       [--feed rithmic|tradovate] [--order conservative|adverse-first]
                       [--attempts 20000] [--days N] [--horizon 120] [--fee 0] [--seed 1] [--json]
  node planner/cli.mjs --firm tradeify [--plan growth|select-flex|select-daily|lightning] [--legacy]
                       [--select-caps-before-2026-09-01] [--payout max|min] (--trades ... [--early-close D,...] | --win ...)
                       [--contracts SPEC | --sweep] [--runs 20000] [--horizon 120] [--seed 1] [--json]

Trade source (one of):
  --trades FILE         TradingView Strategy Tester "List of trades" CSV; whole trading sessions are
                        bootstrapped, including the sessions between the first and last trade with no
                        trades (real trades per session and their order are kept)
    --extra-cost $      extra round-trip cost per contract on top of the CSV P&L (default 0; TradingView
                        P&L already includes the strategy's commission)
    --scale auto|contracts|risk   how a CSV trade is resized: contracts = every trade at the simulated size
                        (fixed-size strategies); risk = every trade at its own as-traded size times the
                        simulated multiplier, capped at the plan's contract limit (strategies that size by
                        dollar risk, like the Eval Lab); auto (default) = risk when trade sizes vary
    --no-merge-legs     keep scale-out exit legs (same side and entry time) as separate trades; by default
                        they are merged into one position so sizing and caps apply to the whole position
    --from DAY --to DAY widen the bootstrap's session pool to DAY..DAY (YYYY-MM-DD), so trade lists from the
                        same data range are compared on the same calendar
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
  --sweep               every size from 1 to the evaluation cap (${cap}); with risk scaling, risk
                        multipliers 1x to the first one at which every trade is capped
  --unit mini|micro     contract unit (default mini)
  --mode eval|pa|both   evaluation, performance account after a pass, or both (default both)
  --feed rithmic|tradovate   evaluation feed; Rithmic/WealthCharts threshold ${stop} (default rithmic)
  --order conservative|adverse-first   intratrade order (default conservative: favorable extreme first;
                        Apex only: with --firm tradeify the order cannot change a result)
  --dll-fill extreme|limit   PA daily-loss flatten at the trade's adverse extreme (default, conservative)
                        or exactly at the limit (platform liquidation; can keep a breach from happening)
  --attempts N          evaluation attempts per size (default 20000)
  --pa-runs N           performance-account runs per size (default: same as --attempts)
  --days N              trading sessions per evaluation attempt (default: the Monday-Friday sessions in
                        the ${e?.accessDays ?? 30}-calendar-day access, ${budgetLabel(rules ? evalSessionBudgets(rules) : null)}, by start weekday)
  --horizon N           PA trading days simulated after a pass (default 120)
  --fee $               evaluation fee per attempt (default 0)
  --seed N              PRNG seed (default 1)
  --rules FILE          rules file (default ${RULES_PATH}; with --firm tradeify ${TRADEIFY_RULES_PATH})
  --json                machine-readable output
  --help                this text

Firm:
  --firm apex|tradeify  apex (default): the evaluation and performance account above; tradeify: the
                        Tradeify 50K Sim Funded account only (no evaluation). --mode, --feed, --attempts,
                        --pa-runs, --days, --fee and --order are Apex options and are rejected with --firm tradeify
  --plan P              Tradeify plan: ${PLAN_KEYS.join(' | ')} (default growth)
  --legacy              Tradeify Growth / Lightning bought before ${String(tradeify?.plans?.growth?.legacyBefore ?? 'the legacy cut-off').slice(0, 10)} (${tradeifyLegacyLabel(tradeify)})
  --select-caps-before-2026-09-01   Select Flex / Select Daily bought before 2026-09-01 (payout caps
                        ${tradeifySelectCapsLabel(tradeify)})
  --payout max|min      request the largest payout allowed (default) or the plan minimum
  --early-close D,D,... (tradeify, with --trades) early-close session days YYYY-MM-DD checked against the
                        ${tradeify?.session?.earlyCloseFlatByEt ?? 'early-close'} ET flat time (the planner has no exchange calendar)
  --runs N              funded accounts simulated per size (default 20000)
  --horizon N           trading sessions simulated per funded account (default 120)
  --sweep               (tradeify) contracts 1 to the plan cap (${tradeifyCapLabel(tradeify)}), or the
                        risk multipliers with --scale risk
  The DLL is soft (the session pauses, --dll-fill applies); payouts are checked at each session close;
  the trader receives ${tradeify ? pct(tradeify.split, 0) : 'the split'} of each payout; --trades replays the actual trades too.

Start from the account you hold (tradeify; read the numbers off the Tradeify dashboard at a session close;
amounts may use commas, and a $ must be quoted: an unquoted $49,000 reaches the planner as 9,000):
  --balance B           balance at the last close; with --floor, every simulated account (and the first
                        replay account) starts here instead of at a fresh ${usd(tradeify?.startBalance ?? 50000)}
  --floor F             current Trailing Max Drawdown floor (${usd(tradeify?.drawdown?.lockedFloor ?? 50100)} once locked; else the highest
                        end-of-day balance - ${usd(tradeify?.drawdown?.amount ?? 2000)}, from ${usd((tradeify?.startBalance ?? 50000) - (tradeify?.drawdown?.amount ?? 2000))} up to below ${usd(tradeify?.drawdown?.lockedFloor ?? 50100)})
  --high-eod H          highest end-of-day balance so far (default: before a payout the largest of B, ${usd(tradeify?.startBalance ?? 50000)}
                        and F + ${usd(tradeify?.drawdown?.amount ?? 2000)}; after one the largest of B, S and the lowest close a payout needs)
  --cycle-start S       balance at the start of this payout cycle: ${usd(tradeify?.startBalance ?? 50000)} before the first payout,
                        otherwise the balance right after the last payout (default ${usd(tradeify?.startBalance ?? 50000)})
  --qual-days N         qualifying days since the last payout (Growth: profit above ${usd(tradeify?.plans?.growth?.payout?.qualifyingDayProfitAbove ?? 150)}; Select Flex:
                        winning days of at least ${usd(tradeify?.plans?.['select-flex']?.payout?.winningDayProfitAtLeast ?? 150)}; default 0, which a qualifying M contradicts)
  --cycle-max-day M     largest profitable day since the last payout. Growth and Lightning (consistency rule)
                        require it when B > S, when N > 0, or before the first payout when H > ${usd(tradeify?.startBalance ?? 50000)};
                        Select Flex uses it only to check N; Select Daily ignores it
  --payouts-taken K     payouts already taken on this account (default 0; the next payout uses tier K+1)
  The run prints the start state, whether a payout could be requested now and what blocks it; payout
  counts and amounts then count from now. A state that is already eligible requests its payout at once:
  that payout is in the payout counts and amounts, and the next-payout columns count the payouts after it.
`;
}

function tradeifyCapLabel(t) {
  if (!t) return 'plan cap';
  const g = t.plans.growth;
  const m = t.microsPerMini;
  const leg = g.legacy?.maxContractsMini;
  return `${g.maxContractsMini} minis / ${g.maxContractsMini * m} micros${leg ? `; legacy ${leg} / ${leg * m}` : ''}`;
}

function tradeifyLegacyLabel(t) {
  const g = t?.plans?.growth?.legacy;
  if (!g) return 'legacy limits';
  return `${g.maxContractsMini} minis, Growth payouts from ${usd(g.minBalance)}`;
}

function tradeifySelectCapsLabel(t) {
  const f = t?.plans?.['select-flex']?.payout;
  const d = t?.plans?.['select-daily']?.payout;
  if (!f || !d) return 'legacy caps';
  return `Flex ${usd(f.capIfBoughtBefore20260901)} instead of ${usd(f.cap)}, Daily ${usd(d.capIfBoughtBefore20260901)} instead of ${usd(d.cap)}`;
}

/** "21" or "21-22" for a list of per-attempt session budgets. */
function budgetLabel(budgets) {
  if (!budgets || budgets.length === 0) return '21-22';
  const lo = Math.min(...budgets);
  const hi = Math.max(...budgets);
  return lo === hi ? `${lo}` : `${lo}-${hi}`;
}

function buildSource(args, rules, { defaultRollHour = SESSION_ROLL_HOUR } = {}) {
  const parametricKeys = ['win', 'rr', 'risk', 'tpd', 'cost', 'loss-r', 'mfe-losers', 'mae-winners', 'r-spread', 'zero-edge'];
  if (args.trades) {
    const clash = parametricKeys.filter((k) => args[k] != null);
    if (clash.length) throw new UsageError(`--trades cannot be combined with ${clash.map((k) => `--${k}`).join(', ')}`);
    const path = resolve(args.trades);
    const rollOff = args['session-roll'] != null && /^(off|none|no|false)$/i.test(String(args['session-roll']));
    const rollHour = rollOff ? null : number(args, 'session-roll', { def: defaultRollHour, min: 0, max: 23, int: true });
    const dateOrder = String(args['date-order'] ?? 'auto').toLowerCase();
    if (!['auto', 'mdy', 'dmy'].includes(dateOrder)) throw new UsageError(`--date-order must be auto, mdy or dmy, got "${args['date-order']}"`);
    const decimal = String(args.decimal ?? 'auto').toLowerCase();
    if (!['auto', '.', ','].includes(decimal)) throw new UsageError(`--decimal must be auto, . or ',', got "${args.decimal}"`);
    const meta = readTvCsv(path, { tz: args.tz ?? NY, rollHour, dateOrder, decimal });
    if (meta.trades.length === 0) throw new UsageError(`no trades could be read from ${path}`);
    const extraCost = number(args, 'extra-cost', { def: 0, min: 0 });
    const scaleArg = String(args.scale ?? 'auto').toLowerCase();
    if (!['auto', 'contracts', 'risk'].includes(scaleArg)) throw new UsageError(`--scale must be auto, contracts or risk, got "${args.scale}"`);
    const legs = args['no-merge-legs'] ? { trades: meta.trades, merged: 0 } : mergeLegs(meta.trades);
    const csvTrades = legs.trades;
    const isoDay = (k) => {
      if (args[k] == null) return null;
      const v = String(args[k]);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(Date.parse(`${v}T00:00:00Z`))) throw new UsageError(`--${k} must be a date YYYY-MM-DD, got "${v}"`);
      return v;
    };
    const from = isoDay('from');
    const to = isoDay('to');
    if (from && to && from > to) throw new UsageError('--from must not be after --to');
    const sizesVary = new Set(csvTrades.map((t) => t.contracts)).size > 1;
    const scaling = scaleArg === 'auto' ? (sizesVary ? 'risk' : 'contracts') : scaleArg;
    const source = makeEmpiricalSource(csvTrades, { extraCost, scaling, from, to });
    const losses = csvTrades.map((t) => t.pnl).filter((x) => x < 0).sort((a, b) => a - b);
    const medianLossAsTraded = losses.length ? losses[Math.floor((losses.length - 1) / 2)] : null;
    return {
      source,
      trades: csvTrades,
      info: {
        kind: 'empirical',
        scaling,
        scaleAuto: scaleArg === 'auto',
        sizesVary,
        minQty: source.minQty,
        maxQty: source.maxQty,
        medianLossAsTraded,
        file: path,
        rows: meta.trades.length,
        legsMerged: legs.merged,
        calendarFrom: from,
        calendarTo: to,
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
  if (args.scale != null) {
    const sc = String(args.scale).toLowerCase();
    if (!['auto', 'contracts', 'risk'].includes(sc)) throw new UsageError(`--scale must be auto, contracts or risk, got "${args.scale}"`);
    if (sc === 'risk') throw new UsageError('--scale risk needs --trades: assumed stats have no as-traded sizes to scale');
  }
  for (const k of ['from', 'to', 'no-merge-legs']) {
    if (args[k] != null) throw new UsageError(`--${k} only applies with --trades`);
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
      scaling: 'contracts',
      zeroEdge: Boolean(args['zero-edge']),
      ...source.params,
      expectancyBeforeCosts: source.expectancyBeforeCosts,
      expectancyPerContract: source.expectancyPerContract,
    },
  };
}

export function run(argv) {
  const args = parseArgs(argv);
  const firm = String(args.firm ?? 'apex').toLowerCase();
  if (!FIRMS.includes(firm)) throw new UsageError(`--firm must be ${FIRMS.join(' or ')}, got "${args.firm}"`);
  if (firm === 'tradeify' && !args.help) return runTradeify(args);
  let rules = null;
  try {
    rules = loadRules(args.rules && firm === 'apex' ? resolve(args.rules) : RULES_PATH);
  } catch (err) {
    if (!args.help) throw err;
  }
  if (args.help) {
    let tradeify = null;
    try {
      tradeify = loadTradeifyRules(args.rules && firm === 'tradeify' ? resolve(args.rules) : TRADEIFY_RULES_PATH);
    } catch {
      // help still prints without the Tradeify rules file
    }
    return { text: usage(rules, tradeify) };
  }
  const tradeifyOnly = TRADEIFY_ONLY.filter((k) => args[k] != null);
  if (tradeifyOnly.length) {
    throw new UsageError(`${tradeifyOnly.map((k) => `--${k}`).join(', ')} only appl${tradeifyOnly.length > 1 ? 'y' : 'ies'} with --firm tradeify`);
  }

  const { source, trades, info } = buildSource(args, rules);
  const unit = asUsage(() => normalizeUnit(args.unit ?? 'mini'));
  const mode = String(args.mode ?? 'both').toLowerCase();
  if (!['eval', 'pa', 'both'].includes(mode)) throw new UsageError(`--mode must be eval, pa or both, got "${args.mode}"`);
  const evalCap = rules.evaluation.maxContractsMini * (unit === 'micro' ? rules.microsPerMini : 1);
  if (args.sweep && args.contracts != null) throw new UsageError('use --contracts or --sweep, not both');
  const risk = source.scaling === 'risk';
  const sizeCap = risk ? Math.max(...defaultSizes(source, evalCap)) : evalCap;
  const sizes =
    args.contracts != null
      ? parseSizes(args.contracts, sizeCap, risk ? 'risk multiplier; beyond it every trade is capped' : 'evaluation cap for this unit')
      : defaultSizes(source, evalCap);
  if (trades) noteOverCap(info, trades, evalCap, unit, 'the evaluation cap');
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
          const r = replayEval(rules, trades, {
            contracts: q,
            scaling: source.scaling,
            feed: settings.feed,
            order: settings.order,
            unit,
            extraCost: info.extraCost,
          });
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
      scaling: source.scaling ?? 'contracts',
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
      ...(s.legsMerged > 0 ? [`exit legs: ${int(s.legsMerged)} scale-out legs merged into their positions (${int(s.rows)} CSV trades -> ${int(s.trades)} positions; --no-merge-legs keeps them apart)`] : []),
      ...(s.calendarFrom || s.calendarTo ? [`calendar: session pool widened to ${s.calendarFrom ?? s.firstDay}..${s.calendarTo ?? s.lastDay} (--from/--to), so sessions without trades at either end are drawn too`] : []),
      s.scaling === 'risk'
        ? `sizing: risk scaling${s.scaleAuto ? ' (auto: trade sizes vary)' : ''}: "Risk x" k = each trade's as-traded size ` +
          `(${int(s.minQty)}-${int(s.maxQty)} ${unitName}s) times k, capped at the plan limit; at 1x the median losing trade lost ` +
          `${s.medianLossAsTraded == null ? '-' : usd(-s.medianLossAsTraded, 2)}`
        : `sizing: fixed contracts: every trade resized to "Qty" ${unitName}s${s.sizesVary ? ' (trade sizes vary in this file; --scale risk keeps them)' : ''}`,
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
  const sizeLabel = s.scaling === 'risk' ? 'Risk x' : 'Qty';
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
        ...(s.scaling === 'risk' ? [pct(v.cappedTradeShare ?? 0)] : []),
        r.contracts === bestPass ? '<- best P(pass)' : '',
      ];
    });
    const head = [sizeLabel, 'P(pass)', 'P(breach)', 'P(expire)', 'Days to pass med/p90', 'Attempts/pass', 'Fees/pass'];
    if (s.scaling === 'risk') head.push('Capped');
    lines.push(table([...head, ''], rows, new Set([head.length])));
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
        [sizeLabel, 'P(1+ payout)', 'Payouts mean/med', 'Paid mean/med', 'P(breach<1st pay)', 'P(pass+payout)*', 'Paid/attempt*', 'Paid/$1 fee*', ''],
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
    lines.push(table([sizeLabel, 'Attempts', 'Passed', 'Breached', 'Expired', 'Open', 'Pass rate'], rows));
  }
  lines.push('', out.summary);
  return lines.join('\n');
}

function summaryLine(out) {
  const s = out.settings;
  const b = out.best;
  const parts = [];
  const plural = (q) =>
    s.scaling === 'risk' ? `risk x${q}` : `${q} ${s.unit === 'micro' ? 'micro' : 'mini'}${q === 1 ? '' : 's'}`;
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

// ---------------------------------------------------------------------------------------------- tradeify

function runTradeify(args) {
  if (args.mode != null && String(args.mode).toLowerCase() !== 'funded') {
    throw new UsageError(
      `--mode ${args.mode} does not apply with --firm tradeify: it simulates the funded account only (no evaluation or Apex PA); drop --mode or use --mode funded`,
    );
  }
  const apexOnly = APEX_ONLY.filter((k) => args[k] != null);
  if (apexOnly.length) {
    const runs = apexOnly.some((k) => k === 'attempts' || k === 'pa-runs') ? '; use --runs N for the number of funded accounts' : '';
    throw new UsageError(
      `${apexOnly.map((k) => `--${k}`).join(', ')} ${apexOnly.length > 1 ? 'are Apex evaluation/PA options' : 'is an Apex evaluation/PA option'}; --firm tradeify simulates the funded account only${runs}`,
    );
  }
  if (args.order != null) {
    throw new UsageError(
      '--order has no effect with --firm tradeify: the end-of-day floor does not move intraday and the favorable extreme never falls below the balance, so both orders give identical results; drop --order',
    );
  }
  if (args['early-close'] != null && !args.trades) throw new UsageError('--early-close only applies with --trades (it checks the CSV trades against the flat time)');
  const earlyCloseDays = args['early-close'] != null ? parseDayList(args['early-close'], '--early-close') : [];
  const rulesFile = args.rules ? resolve(args.rules) : TRADEIFY_RULES_PATH;
  const rules = loadTradeifyRules(rulesFile);
  const planKey = asUsage(() => normalizePlan(args.plan ?? 'growth'));
  const legacy = Boolean(args.legacy);
  const boughtBefore20260901 = Boolean(args['select-caps-before-2026-09-01']);
  const plan = asUsage(() => resolvePlan(rules, planKey, { legacy, boughtBefore20260901 }));
  const startInput = parseStartArgs(args);
  const start = startInput ? asUsage(() => resolveStartState(rules, plan, startInput)) : null;
  const { source, trades, info } = buildSource(args, rules, { defaultRollHour: sessionRollHour(rules) });
  const unit = asUsage(() => normalizeUnit(args.unit ?? 'mini'));
  const cap = planCap(rules, plan, unit);
  if (args.sweep && args.contracts != null) throw new UsageError('use --contracts or --sweep, not both');
  const risk = source.scaling === 'risk';
  const sizeCap = risk ? Math.max(...defaultSizes(source, cap)) : cap;
  if (trades) noteOverCap(info, trades, cap, unit, `the ${plan.name} cap`);
  const sizes =
    args.contracts != null
      ? parseSizes(args.contracts, sizeCap, risk ? `beyond it every trade is capped at the ${plan.name} limit` : `${plan.name} cap for this unit`)
      : defaultSizes(source, cap);
  const settings = asUsage(() => ({
    firm: 'tradeify',
    plan: plan.key,
    legacy,
    selectCapsBefore20260901: boughtBefore20260901,
    payout: normalizePayoutPolicy(args.payout ?? 'max'),
    unit,
    dllFill: normalizeDllFill(args['dll-fill'] ?? 'extreme'),
    runs: number(args, 'runs', { def: 20000, min: 1, int: true }),
    horizonDays: number(args, 'horizon', { def: 120, min: 1, int: true }),
    seed: number(args, 'seed', { def: 1, min: 0, max: 4294967295, int: true }),
  }));
  const simOpts = { ...settings, boughtBefore20260901, ...(start ? { startState: start } : {}) };
  const results = sizes.map((contracts) => simulateFunded(rules, plan.key, source, { ...simOpts, contracts }));
  const replay = trades
    ? sizes.map((contracts) => {
        const r = replayFunded(rules, plan.key, trades, { ...simOpts, contracts, scaling: source.scaling, extraCost: info.extraCost });
        r.accounts = r.accounts.map(({ payoutHistory, ...a }) => ({ ...a, payoutAmounts: payoutHistory.map((p) => p.amount) }));
        return r;
      })
    : null;
  if (trades) {
    const late = flatTimeViolations(rules, trades, NY, earlyCloseDays);
    info.earlyCloseDays = earlyCloseDays;
    info.flatTimeViolations = late.length;
    info.flatTimeTrades = late.map((t) => t.tradeNo);
    info.microscalping = microscalpingCheck(rules, trades, { scaling: source.scaling });
  }
  const startState = start ? startSummary(rules, plan, start, settings, info) : null;
  const best = {
    received: argmaxBy(results, (r) => r.meanReceived),
    payoutChance: argmaxBy(results, (r) => r.pPayout),
  };
  const out = {
    planner: 'tradeify-50k',
    rules: {
      file: rulesFile,
      firm: rules.firm,
      account: rules.account,
      verifiedOn: rules.verifiedOn,
      plan: plan.key,
      planName: plan.name,
      effective: plan,
      drawdown: rules.drawdown,
      split: rules.split,
      session: rules.session,
      fundedRules: rules.fundedRules ?? null,
      unverified: rules.unverified ?? [],
    },
    source: info,
    settings: { ...settings, scaling: source.scaling ?? 'contracts', sizes, cap },
    ...(startState ? { startState } : {}),
    results,
    best: {
      received: best.received ? { contracts: best.received.contracts, meanReceived: best.received.meanReceived } : null,
      payoutChance: best.payoutChance ? { contracts: best.payoutChance.contracts, pPayout: best.payoutChance.pPayout } : null,
    },
    replay,
  };
  out.summary = tradeifySummary(out);
  if (args.json) return { text: JSON.stringify(out, jsonReplacer, 2), data: out };
  return { text: renderTradeify(out, rules), data: out };
}

/** The start-state options as numbers (null when none is given); resolveStartState checks them against the rules. */
export function parseStartArgs(args) {
  const given = START_OPTIONS.filter((k) => args[k] != null);
  if (given.length === 0) return null;
  const missing = ['balance', 'floor'].filter((k) => args[k] == null);
  if (missing.length) {
    throw new UsageError(
      `${missing.map((k) => `--${k}`).join(' and ')} ${missing.length > 1 ? 'are' : 'is'} required to start from your current account ` +
        `(given: ${given.map((k) => `--${k}`).join(', ')}); read ${missing.length > 1 ? 'them' : 'it'} off the Tradeify dashboard at a session close`,
    );
  }
  return {
    balance: number(args, 'balance', { min: 0, gt: true }),
    floor: number(args, 'floor', { min: 0, gt: true }),
    highEod: number(args, 'high-eod', { min: 0, gt: true }),
    cycleStart: number(args, 'cycle-start', { min: 0, gt: true }),
    qualDays: number(args, 'qual-days', { def: 0, min: 0, int: true }),
    cycleMaxDay: number(args, 'cycle-max-day', { min: 0 }),
    payoutsTaken: number(args, 'payouts-taken', { def: 0, min: 0, int: true }),
  };
}

/**
 * The start state for output: the resolved state, the next payout, whether a payout could be requested now
 * (and what blocks it), and the payout gates the ledger does not model (from fundedRules).
 */
function startSummary(rules, plan, start, settings, info) {
  const L = makeFundedLedger(rules, plan.key, {
    legacy: plan.legacy,
    boughtBefore20260901: plan.boughtBefore20260901,
    payout: settings.payout,
    dllFill: settings.dllFill,
    startState: start,
  });
  const c = payoutCheck(L);
  const fr = rules.fundedRules ?? {};
  const alsoNeeded = [];
  const ms = info.microscalping;
  // Rules the ledger does not model that block a payout now on the evidence given (the --trades list).
  const blockedBy = fr.microscalping && ms && !ms.passes ? ['microscalping'] : [];
  if (fr.microscalping) {
    const status = ms ? (ms.passes ? 'the --trades list passes it' : 'the --trades list fails it') : 'not checked without --trades';
    alsoNeeded.push({ rule: 'microscalping', text: fr.microscalping, status });
  }
  if (fr.kyc && start.payoutsTaken === 0) alsoNeeded.push({ rule: 'kyc', text: fr.kyc, status: null });
  if (fr.payoutApproval) alsoNeeded.push({ rule: 'payoutApproval', text: fr.payoutApproval, status: null });
  const { kind: _kind, planKey: _planKey, legacy: _legacy, ...state } = start;
  return {
    ...state,
    nextPayout: c.n,
    nextCap: c.cap ?? null,
    payoutNow: {
      eligible: c.eligible,
      amount: c.eligible ? c.amount : 0,
      maxAmount: c.maxAmount,
      checks: c.checks,
      blockers: payoutBlockers(L, c),
      blockedBy, // the simulation and replay still request it, as if these rules were met
      ...(blockedBy.length ? { minHoldSeconds: ms.minHoldSeconds } : {}),
    },
    alsoNeeded,
  };
}

/** Text lines for the start state (under "Start  :"). */
function startLines(st, rules, plan) {
  const d = rules.drawdown;
  const P = plan.payout;
  const lock = st.locked
    ? `locked at ${usd(d.lockedFloor)}: ${st.lockedBy === 'eod' ? `an end-of-day balance reached ${usd(d.lockTriggerEodBalance)}` : 'a payout was requested'}`
    : `trails ${usd(d.amount)} below the highest end-of-day balance ${usd(st.highEod, 2)}; locks at ${usd(d.lockedFloor)} once a close reaches ` +
      `${usd(d.lockTriggerEodBalance)}${d.lockOnPayoutRequest ? ' or a payout is requested' : ''}`;
  const dll = st.dll == null ? `no DLL${st.dllRaised ? ' (removed)' : ''}` : `DLL ${usd(st.dll)}${st.dllRaised ? ' (raised)' : ''}`;
  // The largest day matters only to a consistency rule (Growth, Lightning).
  const largest = plan.consistency != null
    ? `, largest day ${usd(st.cycleMaxDay, 2)}${st.cycleProfit > 0 && st.cycleMaxDay > 0 ? ` (${pct(st.cycleMaxDay / st.cycleProfit)} of the profit)` : ''}`
    : '';
  const dayCount = (n, need, kind) => `, ${n} ${kind} day${n === 1 ? '' : 's'} (${need} needed)`;
  const days =
    P.type === 'growth'
      ? dayCount(st.qualDays, P.minQualifyingDays, 'qualifying')
      : P.type === 'select-flex'
        ? dayCount(st.qualDays, P.winningDays, 'winning')
        : '';
  const cap = st.nextCap != null ? `, cap ${usd(st.nextCap)}` : '';
  const pn = st.payoutNow;
  const lines = [
    `Start  : your account now: balance ${usd(st.balance, 2)}, floor ${usd(st.floor, 2)} (${lock}), room to floor ${usd(st.roomToFloor, 2)}; ${dll}`,
    `         since the last payout (cycle start ${usd(st.cycleStart, 2)}): profit ${usd(st.cycleProfit, 2)}${largest}${days}; ` +
      `${st.payoutsTaken} payout${st.payoutsTaken === 1 ? '' : 's'} taken, next is payout ${st.nextPayout}${cap}`,
  ];
  const now = `${usd(pn.amount, 2)} (payout ${st.nextPayout})`;
  const after = 'the next-payout columns below count the payouts after it';
  if (!pn.eligible) lines.push(`         payout now: no - ${pn.blockers.map((b) => b.message).join('; ')}`);
  else if (pn.blockedBy.includes('microscalping')) {
    lines.push(
      `         payout now: blocked by the ${pn.minHoldSeconds}-second rule, which the --trades list fails; the payout rules alone allow ${now}. ` +
        `The run still requests it at once, as if the rule were met; ${after}`,
    );
  } else lines.push(`         payout now: yes, ${now}; the run requests it at once, before the first simulated session; ${after}`);
  if (st.alsoNeeded.length) {
    lines.push(`         also needed (not modelled): ${st.alsoNeeded.map((a) => (a.status ? `${a.text} (${a.status})` : a.text)).join('; ')}`);
  }
  for (const w of st.warnings) lines.push(`         WARNING: ${w}`);
  for (const n of st.notes) lines.push(`         note: ${n}`);
  return lines;
}

function argmaxBy(rows, f) {
  let best = null;
  let bestV = -Infinity;
  for (const r of rows) {
    const v = f(r);
    if (v != null && v > bestV) {
      bestV = v;
      best = r;
    }
  }
  return best && bestV > 0 ? best : null;
}

const list$ = (arr) => arr.map((x) => usd(x)).join('/');
const listPct = (arr) => arr.map((x) => pct(x, 0)).join('/');

/** The plan's rules in two lines: account limits, then the payout rule. */
export function tradeifyRuleLines(rules, plan, unit) {
  const d = rules.drawdown;
  const m = rules.microsPerMini;
  const startFloor = rules.startBalance - d.amount;
  const lockBits = [`an EOD balance reaches ${usd(d.lockTriggerEodBalance)}`];
  if (d.lockOnPayoutRequest) lockBits.push('a payout is requested');
  let dll = 'no DLL';
  if (plan.dailyLossLimit != null) {
    dll = `DLL ${usd(plan.dailyLossLimit)} soft (pauses the session)`;
    if (plan.dllRaise) {
      dll += plan.dllRaise.to == null
        ? `, removed after a ${usd(plan.dllRaise.atBalance)} close`
        : `, ${usd(plan.dllRaise.to)} after a ${usd(plan.dllRaise.atBalance)} close`;
    }
  }
  const capText = plan.scaling
    ? `contracts ${plan.scaling.map((t) => t.maxContractsMini).join('/')} minis at EOD profit ${plan.scaling
        .map((t, i) => (i === 0 ? `< ${usd(plan.scaling[1]?.minProfit ?? Infinity)}` : `>= ${usd(t.minProfit)}`))
        .join(' / ')} (kept once reached)`
    : `max ${plan.maxContractsMini} minis / ${plan.maxContractsMini * m} micros`;
  const line1 =
    `EOD trailing drawdown ${usd(d.amount)} (floor ${usd(startFloor)}, locks at ${usd(d.lockedFloor)} once ${lockBits.join(' or ')}); ` +
    `${dll}; ${capText}; flat by ${rules.session.flatByEt} ET (${rules.session.earlyCloseFlatByEt} ET on early-close days)`;
  const P = plan.payout;
  const repeat = (caps, rep) => (P.capAfterTiers != null ? `, then ${usd(P.capAfterTiers)}` : rep !== false ? `, then ${usd(caps[caps.length - 1])}` : '');
  let line2;
  if (P.type === 'growth') {
    line2 =
      `payout: ${P.minQualifyingDays} days > ${usd(P.qualifyingDayProfitAbove)} since the last payout, largest day <= ${listPct(plan.consistency)} of profit since the last payout, ` +
      `balance >= ${usd(P.minBalance)}; amount min(${list$(P.caps)}${repeat(P.caps, P.capsRepeatLast)}, balance - floor - $0.01) >= ${usd(P.minPayout)}`;
  } else if (P.type === 'select-flex') {
    line2 =
      `payout: ${P.winningDays} winning days (>= ${usd(P.winningDayProfitAtLeast)}) since the last payout, positive profit since the last payout from payout ${P.positiveCycleProfitFromPayout}; ` +
      `amount min(${pct(P.shareOfTotalProfit, 0)} of total profit, ${usd(P.cap)}) >= ${usd(P.minPayout)}, balance stays above the floor`;
  } else if (P.type === 'select-daily') {
    line2 =
      `payout: daily, profit since the last payout > 0; amount min(${P.multipleOfCycleProfit}x profit since the last payout, ${usd(P.cap)}, balance - ${usd(P.bufferBalance)}) >= ${usd(P.minPayout)}`;
  } else {
    line2 =
      `payout: profit since the last payout >= ${list$(P.profitGoals)} (payout 1, then each later), largest day <= ${listPct(plan.consistency)} of it by payout number; ` +
      `amount min(${list$(P.caps)}${repeat(P.caps, P.capsRepeatLast)}, balance - floor - $0.01) >= ${usd(P.minPayout)}`;
  }
  return [line1, `${line2}; trader receives ${pct(rules.split, 0)}`];
}

function renderTradeify(out, rules) {
  const s = out.settings;
  const plan = out.rules.effective;
  const unitName = s.unit === 'micro' ? 'micro' : 'mini';
  const sizeLabel = s.scaling === 'risk' ? 'Risk x' : 'Qty';
  const lines = [];
  const src = describeSource(out.source, unitName);
  lines.push(`Tradeify 50K funded planner - ${rules.firm} ${plan.name} (${rules.account}; rules verified ${rules.verifiedOn})`);
  lines.push(`Trades : ${src[0]}`);
  for (const l of src.slice(1)) lines.push(`         ${l}`);
  const csv = out.source.kind === 'empirical';
  const early = out.source.earlyCloseDays ?? [];
  const earlyText = early.length
    ? `${rules.session.earlyCloseFlatByEt} ET on the ${early.length} --early-close day(s)`
    : `early-close days (${rules.session.earlyCloseFlatByEt} ET) not checked: list them with --early-close YYYY-MM-DD,...`;
  if (out.source.flatTimeViolations > 0) {
    lines.push(
      `         WARNING: ${out.source.flatTimeViolations} trade(s) (#${out.source.flatTimeTrades.join(', #')}) were open after the ${rules.session.flatByEt} ET flat time ` +
        `or across the session break (${earlyText}); they are simulated as traded`,
    );
  } else if (csv) {
    lines.push(`         flat time: no trade open after ${rules.session.flatByEt} ET or across the session break (${earlyText})`);
  }
  const ms = out.source.microscalping;
  if (ms && !ms.passes) {
    const same = ms.sameTimestamp > 0 ? `; ${ms.sameTimestamp} trade(s) open and close on the same CSV timestamp and count as 0 s` : '';
    lines.push(
      `         WARNING: microscalping: ${pct(ms.longShareOfTrades)} of trades and ${pct(ms.longShareOfProfit)} of gross profit come from holds over ${ms.minHoldSeconds} s ` +
        `(Tradeify blocks payouts unless both are over ${pct(ms.minShare, 0)}${same}); the simulation and replay pay out as if the rule were met`,
    );
  }
  const [r1, r2] = tradeifyRuleLines(rules, plan, s.unit);
  lines.push(`Rules  : ${r1}`);
  lines.push(`         ${r2}`);
  const notModelled = [];
  if (rules.fundedRules?.minActivity) notModelled.push(`minimum activity (${rules.fundedRules.minActivity})`);
  if (!csv) notModelled.push('flat time and microscalping (checked on --trades only)');
  if (notModelled.length) lines.push(`         not modelled: ${notModelled.join('; ')}`);
  const unverified = out.rules.unverified.length;
  lines.push(
    `Run    : ${int(s.runs)} funded accounts x ${s.horizonDays} trading sessions; DLL fill ${s.dllFill}; payout ${s.payout}; ` +
      `unit ${unitName}; seed ${s.seed}${unverified ? `; ${unverified} modelling assumptions listed under "unverified" in the rules file` : ''}`,
  );
  const fromStart = Boolean(out.startState);
  if (fromStart) lines.push(...startLines(out.startState, rules, plan));
  const bestRec = out.best.received?.contracts;
  const bestChance = out.best.payoutChance?.contracts;
  const now = out.results[0]?.payoutNow;
  lines.push(
    '',
    fromStart
      ? `FUNDED ACCOUNT from the start state above (${s.horizonDays} more trading sessions per account; payouts from now on; "To trader" = requested x ${pct(rules.split, 0)})`
      : `FUNDED ACCOUNT (${s.horizonDays} trading sessions per account; "To trader" = requested x ${pct(rules.split, 0)})`,
  );
  if (now) {
    lines.push(
      `Payouts, Requested and To trader include the ${usd(now.amount, 2)} payout ${now.n} requested now (same in every run); ` +
        'P(1+ more payout), P(breach<next pay) and Days to next pay count only the payouts after it',
    );
  }
  const rows = out.results.map((r) => {
    const tags = [];
    if (r.contracts === bestRec) tags.push('best $ to trader');
    if (r.contracts === bestChance) tags.push('best P(payout)');
    return [
      r.contracts,
      pct(r.pPayout),
      `${fx(r.meanPayouts, 2)}/${r.medianPayouts}`,
      `${usd(r.meanRequested)}/${usd(r.medianRequested)}`,
      `${usd(r.meanReceived)}/${usd(r.medianReceived)}`,
      pct(r.pBreachBeforeFirstPayout),
      pct(r.pBreach),
      r.medianDaysToFirstPayout == null ? '-' : r.medianDaysToFirstPayout,
      fx(r.dllDaysPerRun, 2),
      pct(r.cappedTradeShare),
      tags.length ? `<- ${tags.join(', ')}` : '',
    ];
  });
  const heads = fromStart
    ? [sizeLabel, 'P(1+ more payout)', 'Payouts mean/med', 'Requested mean/med', 'To trader mean/med', 'P(breach<next pay)', 'P(breach)', 'Days to next pay', 'DLL days/run', 'Capped', '']
    : [sizeLabel, 'P(1+ payout)', 'Payouts mean/med', 'Requested mean/med', 'To trader mean/med', 'P(breach<1st pay)', 'P(breach)', 'Days to 1st pay', 'DLL days/run', 'Capped', ''];
  lines.push(table(heads, rows, new Set([10])));
  lines.push(
    fromStart
      ? `Days to next pay = median trading sessions from now to the next payout${now ? ' after the one requested now' : ''} among accounts that got one; Capped = share of trades cut to the plan cap`
      : 'Days to 1st pay = median trading sessions to the first payout among accounts that got one; Capped = share of trades cut to the plan cap',
  );
  if (out.replay) {
    const r0 = out.replay[0];
    lines.push(
      '',
      `HISTORICAL REPLAY (actual trade order, ${r0.firstDay}..${r0.lastDay}, ${r0.sessions} sessions; ` +
        `${fromStart ? 'the first account starts from the start state above, 1st payout "start" = the payout requested now; ' : ''}a breach ends the account and a fresh one starts at the next session)`,
    );
    const rows2 = out.replay.map((r) => [
      r.contracts,
      r.total,
      r.breached,
      r.payouts,
      usd(r.requested),
      usd(r.received),
      r.firstPayoutDay ?? '-',
      r.dllDays,
      lastAccount(r.last),
    ]);
    lines.push(table([sizeLabel, 'Accounts', 'Breached', 'Payouts', 'Requested', 'To trader', '1st payout', 'DLL days', 'Last account'], rows2, new Set([8])));
  }
  lines.push('', out.summary);
  return lines.join('\n');
}

function lastAccount(a) {
  if (!a) return '-';
  const floor = `floor ${usd(a.floor, 2)}${a.locked ? ' (locked)' : ''}`;
  if (a.status === 'BREACHED') return `BREACHED ${a.breachDay}: net liq ${usd(a.breachNetLiq, 2)} <= ${floor}`;
  return `${a.status} balance ${usd(a.balance, 2)}, ${floor}`;
}

function tradeifySummary(out) {
  const s = out.settings;
  const name = out.rules.planName;
  const label = (q) => (s.scaling === 'risk' ? `risk x${q}` : `${q} ${s.unit === 'micro' ? 'micro' : 'mini'}${q === 1 ? '' : 's'}`);
  const find = (q) => out.results.find((r) => r.contracts === q);
  const parts = [];
  const st = out.startState;
  const now = out.results[0]?.payoutNow;
  const nowText = now ? ` after the ${usd(now.amount, 2)} payout ${now.n} requested now` : '';
  const [one, first, within] = st ? [`one more payout${nowText}`, 'it', `the next ${s.horizonDays}`] : ['one payout', 'the first', `${s.horizonDays}`];
  if (out.best.received) {
    const r = find(out.best.received.contracts);
    parts.push(
      `${label(r.contracts)} pays the trader the most (${usd(r.meanReceived)} on average within ${within} trading sessions${now ? ', including the payout now' : ''}; ` +
        `${pct(r.pPayout)} reach at least ${one}, ${pct(r.pBreachBeforeFirstPayout)} breach before ${first})`,
    );
    if (out.best.payoutChance && out.best.payoutChance.contracts !== r.contracts) {
      const c = find(out.best.payoutChance.contracts);
      parts.push(`${label(c.contracts)} gives the best chance of a payout (${pct(c.pPayout)}, ${usd(c.meanReceived)} to the trader on average)`);
    }
  } else parts.push(`no size reached a${st ? 'nother' : ''} payout${nowText} within ${within} trading sessions`);
  if (out.replay) {
    // A payout requested at the start state is not one the replayed trades earned.
    const paid = out.replay.filter((r) => r.payouts - (r.startPayouts ?? 0) > 0);
    const replayNow = out.replay.some((r) => r.startPayouts > 0) ? ' after the payout requested now' : '';
    parts.push(
      paid.length
        ? `the historical replay paid out${replayNow} at ${paid.map((r) => label(r.contracts)).join(', ')}`
        : `the historical replay reached no payout${replayNow} at any size`,
    );
  }
  const from = st ? ` from your account now (balance ${usd(st.balance, 2)}, floor ${usd(st.floor, 2)}, next payout ${st.nextPayout})` : '';
  let text = `Summary: ${name}${from}: ${parts.join('; ')}.`;
  const ex = out.source.expectancyPerContract;
  if (Math.abs(ex) < 1e-9) text += ' Expectancy after costs is zero, so these odds come from variance alone.';
  else if (ex < 0) text += ` Expectancy after costs is negative (${usd(ex, 2)} per trade per contract): payouts here are luck, not edge.`;
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
