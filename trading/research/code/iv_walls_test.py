"""IV Walls fade test per PREREG.md. Usage: python3 -I iv_walls_test.py NSX_1m.npz VXNCLS.csv OUT.json"""
import sys, json, math
import numpy as np, pandas as pd
from scipy import stats
npz, vxn_csv, out = sys.argv[1:4]
COST, SLIP, TICK, SPLIT = 0.75, 0.25, 0.25, pd.Timestamp('2020-03-18').date()
z = np.load(npz); t = z['t']; O = z['o']; H = z['h']; L = z['l']; C = z['c']
et = pd.to_datetime(t, unit='s', utc=True).tz_convert('America/New_York')
mins = (et.hour * 60 + et.minute).to_numpy(); dates = et.date
# trading day D for each bar: bars at/after 18:00 belong to the next calendar day
import datetime as _dt
_one = _dt.timedelta(days=1)
tday = np.array([(d + _one) if m >= 1080 else d for d, m in zip(dates, mins)], dtype=object)   # all datetime.date
use = (mins < 960) | (mins >= 1080)               # 18:00 .. 15:59 ET only
idx_by_day = {}
for i in np.nonzero(use)[0]:
    idx_by_day.setdefault(tday[i], []).append(i)
rth = (mins >= 570) & (mins < 960)
rth_count = pd.Series(1, index=pd.Index(dates[rth])).groupby(level=0).size()
close16 = pd.Series(C[mins == 959], index=pd.Index(dates[mins == 959])).groupby(level=0).last()
complete = set(rth_count[rth_count >= 370].index)
days = sorted(d for d in idx_by_day if d in complete and d in close16.index)
vx = pd.read_csv(vxn_csv); vx.columns = ['date', 'vxn']; vx['vxn'] = pd.to_numeric(vx.vxn, errors='coerce'); vx = vx.dropna()
vxn = pd.Series(vx.vxn.values, index=pd.to_datetime(vx.date).dt.date)
c16 = close16.sort_index()
lr = np.log(c16).diff()
hv20 = (lr.rolling(20).std() * math.sqrt(252) * 100)   # annualised %, known at that day's close

def sim(i0, idx, wall, side, stop_d, tgt_px):
    """side=-1 short at upper wall, +1 long at lower wall. Returns (net, mae, reason) or None."""
    o, h, l, c = O[idx], H[idx], L[idx], C[idx]
    if (side == -1 and o[i0] >= wall) or (side == 1 and o[i0] <= wall): return None
    thr = (h[i0:] > wall) if side == -1 else (l[i0:] < wall)
    if not thr.any(): return 'untouched'
    e = i0 + int(np.argmax(thr))
    entry = wall
    if side == -1 and o[e] > wall: entry = o[e]
    if side == 1 and o[e] < wall: entry = o[e]
    stop = wall - side * stop_d
    mae = 0.0
    for j in range(e, len(o)):
        adverse = (h[j] - entry) if side == -1 else (entry - l[j])
        if j > e:
            if (side == -1 and o[j] >= stop) or (side == 1 and o[j] <= stop):
                px = o[j] - side * SLIP; return (side * (px - entry) - COST, max(mae, abs(o[j] - entry)), 'stop_gap')
        if (side == -1 and h[j] >= stop) or (side == 1 and l[j] <= stop):
            px = stop - side * SLIP; return (side * (px - entry) - COST, max(mae, abs(stop - entry)), 'stop')
        mae = max(mae, adverse)
        if j > e and ((side == -1 and l[j] < tgt_px) or (side == 1 and h[j] > tgt_px)):
            return (side * (tgt_px - entry) - COST, mae, 'target')
    return (side * (c[-1] - entry) - COST, mae, 'eod')

def run(window, stop_f, tgt, vol='vxn'):
    rows = []; touch = 0; beyond = 0; nd = 0
    for k in range(1, len(days)):
        D, P = days[k], days[k - 1]
        v = vxn.get(P) if vol == 'vxn' else hv20.get(P)
        if v is None or not np.isfinite(v): continue
        ref = float(c16[P]); em = ref * v / 100.0 / math.sqrt(252)
        idx = np.array(idx_by_day[D]); m = mins[idx]
        if window == 'RTH':
            st = np.nonzero(m == 570)[0]
            if len(st) == 0: continue
            i0 = int(st[0])
        else: i0 = 0
        nd += 1; hit = False
        for side, wall in ((-1, ref + em), (1, ref - em)):
            stop_d = stop_f * em
            if tgt == '5R': tp = wall + side * 5 * stop_d
            elif tgt == '1R': tp = wall + side * 1 * stop_d
            elif tgt == 'REF': tp = ref
            else: tp = wall + side * float(tgt) * em
            r = sim(i0, idx, wall, side, stop_d, tp)
            if r is None or r == 'untouched':
                if r is None: hit = True
                continue
            hit = True
            rows.append((D, side, r[0], r[1], r[2], em))
        touch += hit
        cl = C[idx[-1]]
        beyond += (cl > ref + em) or (cl < ref - em)
    df = pd.DataFrame(rows, columns=['day', 'side', 'net', 'mae', 'reason', 'em'])
    return df, nd, touch, beyond

def st(df):
    n = len(df)
    if n < 2: return {'n': n}
    x = df.net.to_numpy(); m = x.mean(); sd = x.std(ddof=1); tt = m / (sd / math.sqrt(n))
    daily = df.groupby('day').net.sum(); dt = daily.mean() / (daily.std(ddof=1) / math.sqrt(len(daily)))
    return {'n': n, 'mean_net_pts': round(m, 2), 't': round(tt, 2), 'p_one_sided': float(stats.t.sf(tt, n - 1)), 't_by_day': round(float(dt), 2),
            'win_rate': round(float((x > 0).mean()), 3), 'avg_win': round(float(x[x > 0].mean()), 1) if (x > 0).any() else None,
            'avg_loss': round(float(x[x <= 0].mean()), 1) if (x <= 0).any() else None, 'total_pts': round(float(x.sum()), 0),
            'mae_p50': round(float(df.mae.median()), 1), 'mae_p90': round(float(df.mae.quantile(0.9)), 1), 'median_em': round(float(df.em.median()), 1),
            'exits': df.reason.value_counts().to_dict()}

res = {'variants': [], 'notes': {}}
for window in ['FULL', 'RTH']:
    for stop_f in [0.10, 0.25]:
        for tgt in ['5R', 'REF', '1R']:
            df, nd, touch, beyond = run(window, stop_f, tgt)
            res['variants'].append({'id': f'{window}|stop{stop_f}|{tgt}', 'all': st(df), 'is': st(df[df.day < SPLIT]), 'oos': st(df[df.day >= SPLIT]),
                                    'days': int(nd), 'days_touch_or_open_beyond': int(touch), 'days_close_beyond': int(beyond),
                                    'oos_by_year': {int(k): round(float(v), 0) for k, v in df[df.day >= SPLIT].groupby(df[df.day >= SPLIT].day.map(lambda d: d.year)).net.sum().items()}})
df, nd, touch, beyond = run('FULL', 0.50, '0.10')
res['highwin'] = {'id': 'FULL|stop0.5EM|target0.10EM', 'all': st(df), 'is': st(df[df.day < SPLIT]), 'oos': st(df[df.day >= SPLIT])}
df, nd2, t2, b2 = run('FULL', 0.10, '5R', vol='hv')
res['placebo_hv20'] = {'id': 'FULL|stop0.1|5R with 20-day historical volatility', 'all': st(df), 'is': st(df[df.day < SPLIT]), 'oos': st(df[df.day >= SPLIT]), 'days': int(nd2), 'days_touch': int(t2), 'days_close_beyond': int(b2)}
# Holm over the 12 variants' OOS p-values
ps = sorted([(v['oos'].get('p_one_sided', 1.0), v['id']) for v in res['variants']]); mtests = len(ps); runmax = 0; holm = {}
for i, (p, vid) in enumerate(ps):
    runmax = max(runmax, min(1.0, (mtests - i) * p)); holm[vid] = runmax
for v in res['variants']: v['oos_p_holm'] = holm[v['id']]
res['notes'] = {'median_bars_per_session': int(np.median([len(idx_by_day[d]) for d in days])), 'first_day': str(days[1]), 'last_day': str(days[-1]), 'days_tested_full': res['variants'][0]['days']}
json.dump(res, open(out, 'w'), indent=1, default=str)
print('written', out)
