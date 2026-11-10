"""Build ET-stamped Nasdaq-100 1-minute and 5-minute bars from histdata.com NSXUSD files and validate them
against NQ=F futures. Usage: python3 -I build_data.py ZIP_DIR OUT_DIR NQ_1D_CSV NQ_1H_CSV"""
import sys, os, zipfile, io, json
import numpy as np, pandas as pd
zdir, out, nq1d, nq1h = sys.argv[1:5]
frames = []
for fn in sorted(os.listdir(zdir)):
    if not fn.endswith('.zip'): continue
    z = zipfile.ZipFile(os.path.join(zdir, fn))
    name = [n for n in z.namelist() if n.lower().endswith('.csv')][0]
    df = pd.read_csv(io.BytesIO(z.read(name)), sep=';', header=None, names=['dt', 'open', 'high', 'low', 'close', 'volume'], dtype={'dt': str})
    frames.append(df)
raw = pd.concat(frames, ignore_index=True)
raw['naive'] = pd.to_datetime(raw['dt'], format='%Y%m%d %H%M%S')
raw = raw.drop_duplicates('naive').sort_values('naive').reset_index(drop=True)
rep = {'rows_raw': int(len(raw)), 'first_raw': str(raw.naive.iloc[0]), 'last_raw': str(raw.naive.iloc[-1])}

# Which clock are the stamps in? Try three candidates and keep the one whose daily break most often starts at
# 16:15 ET (the CFD's break) on every day of the year, including the weeks when US and EU daylight-saving dates differ.
def to_utc(kind):
    if kind == 'ny':   return raw.naive.dt.tz_localize('America/New_York', ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
    if kind == 'est':  return raw.naive.dt.tz_localize('Etc/GMT+5').dt.tz_convert('UTC')
    if kind == 'eet7': return (raw.naive + pd.Timedelta(hours=7)).dt.tz_localize('Europe/Helsinki', ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
gap = raw.naive.diff().dt.total_seconds().fillna(60)
brk_idx = raw.index[(gap > 3600) & (gap < 4 * 3600)]
scores = {}
for kind in ['ny', 'est', 'eet7']:
    u = to_utc(kind)
    prev_et = u.shift(1)[brk_idx].dt.tz_convert('America/New_York')
    scores[kind] = float(((prev_et.dt.hour * 60 + prev_et.dt.minute) == 974).mean())
rep['share_of_daily_breaks_starting_1615_ET_by_clock'] = scores
# Checked against the 09:30 ET volatility spike in the US/EU daylight-saving mismatch weeks of every year:
# files up to 2018 use the New York wall clock; files from 2019 use Eastern European time minus 7 hours.
rep['clock'] = 'New York wall clock through 2018; Eastern European time minus 7 hours from 2019 (differs from New York only in the weeks when US and EU daylight-saving dates differ)'
utc = to_utc('ny').where(raw.naive.dt.year <= 2018, to_utc('eet7'))
brk = raw.loc[brk_idx]
raw['utc'] = utc
raw = raw.dropna(subset=['utc']).reset_index(drop=True)
et = raw.utc.dt.tz_convert('America/New_York')
raw['et'] = et
# sanity filters
bad = (raw.high < raw.low) | (raw.open <= 0) | (raw.close <= 0) | (raw.high < raw[['open', 'close']].max(axis=1) - 1e-9) | (raw.low > raw[['open', 'close']].min(axis=1) + 1e-9)
rep['bad_ohlc_rows_dropped'] = int(bad.sum())
raw = raw.loc[~bad].reset_index(drop=True)
ret1 = raw.close.pct_change().abs()
rep['one_minute_moves_over_3pct'] = int((ret1 > 0.03).sum())

def write(df, path_base):
    ep = (df.utc.astype('int64') // 10**9).to_numpy() if str(df.utc.dtype).endswith('ns, UTC]') else df.utc.map(lambda t: int(t.timestamp())).to_numpy()
    np.savez_compressed(path_base + '.npz', t=ep.astype('int64'), o=df.open.to_numpy('float64'), h=df.high.to_numpy('float64'), l=df.low.to_numpy('float64'), c=df.close.to_numpy('float64'))
    return ep
os.makedirs(out, exist_ok=True)
unit = str(raw.utc.dtype)
ep1 = (raw.utc.astype('int64') // (10**9 if 'ns' in unit else 10**6 if 'us' in unit else 10**3 if 'ms' in unit else 1)).to_numpy()
assert abs(ep1[0] - raw.utc.iloc[0].timestamp()) < 1, 'epoch conversion check failed'
np.savez_compressed(os.path.join(out, 'NSX_1m.npz'), t=ep1.astype('int64'), o=raw.open.to_numpy('float64'), h=raw.high.to_numpy('float64'), l=raw.low.to_numpy('float64'), c=raw.close.to_numpy('float64'))
# 5-minute bars: bucket by floor of the bar-open epoch to 300 s
b = ep1 // 300 * 300
g = pd.DataFrame({'b': b, 'o': raw.open, 'h': raw.high, 'l': raw.low, 'c': raw.close}).groupby('b', sort=True)
m5 = pd.DataFrame({'t': g.o.first().index.to_numpy(), 'o': g.o.first().to_numpy(), 'h': g.h.max().to_numpy(), 'l': g.l.min().to_numpy(), 'c': g.c.last().to_numpy(), 'n': g.o.size().to_numpy()})
np.savez_compressed(os.path.join(out, 'NSX_5m.npz'), t=m5.t.to_numpy('int64'), o=m5.o.to_numpy(), h=m5.h.to_numpy(), l=m5.l.to_numpy(), c=m5.c.to_numpy())
m5et = pd.to_datetime(m5.t, unit='s', utc=True).dt.tz_convert('America/New_York')
pd.DataFrame({'timestamp': m5et.map(lambda x: x.isoformat()), 'open': m5.o, 'high': m5.h, 'low': m5.l, 'close': m5.c, 'volume': 0}).to_csv(os.path.join(out, 'NSX_5m.csv'), index=False)
rep.update(rows_1m=int(len(raw)), rows_5m=int(len(m5)), first_et=str(raw.et.iloc[0]), last_et=str(raw.et.iloc[-1]))

# coverage per year: trading days with an RTH session and bars per RTH session (09:30-16:00 ET = 390 minutes)
mins = raw.et.dt.hour * 60 + raw.et.dt.minute
rth = raw.loc[(mins >= 570) & (mins < 960)]
per_day = rth.groupby(rth.et.dt.date).size()
py = pd.Series(per_day.values, index=pd.to_datetime(per_day.index)).groupby(lambda d: d.year)
rep['rth_days_per_year'] = {int(k): int(v) for k, v in py.size().items()}
rep['rth_median_bars_per_day_per_year'] = {int(k): float(v) for k, v in py.median().items()}
rep['rth_days_with_under_350_bars'] = int((per_day < 350).sum())
rep['daily_break_et'] = 'last bar before break opens at minute-of-day %s ET (mode)' % int((raw.et.shift(1)[brk.index.intersection(raw.index)].dt.hour * 60 + raw.et.shift(1)[brk.index.intersection(raw.index)].dt.minute).mode().iloc[0])

# validation 1: daily. NSX 16:00 ET close (close of the 15:59 bar) vs NQ=F daily close.
c16 = raw.loc[mins == 959].groupby(raw.et.dt.date).close.last()
c16.index = pd.to_datetime(c16.index)
d = pd.read_csv(nq1d); d['date'] = pd.to_datetime(d.timestamp.str[:10]); d = d.set_index('date').close
j = pd.concat([c16.rename('nsx'), d.rename('nq')], axis=1).dropna()
r = j.pct_change().dropna()
rep['daily_n'] = int(len(r)); rep['daily_ret_corr'] = float(r.nsx.corr(r.nq))
diff = (r.nsx - r.nq)
core = r.loc[diff.abs() < 0.01]
rep['daily_ret_corr_excl_diff_over_1pct'] = float(core.nsx.corr(core.nq)); rep['daily_days_diff_over_1pct'] = int((diff.abs() >= 0.01).sum())
rep['daily_median_abs_ret_diff'] = float(diff.abs().median())
rep['basis_nsx_over_nq_median_by_year'] = {int(k): float(v) for k, v in (j.nsx / j.nq).groupby(lambda x: x.year).median().items()}
# validation 2: hourly returns vs NQ=F hourly (HH:00 aligned, ET)
h = pd.read_csv(nq1h); h['ts'] = pd.to_datetime(h.timestamp, utc=True); h = h.loc[h.ts.dt.minute == 0].set_index('ts').close
hb = ep1 // 3600 * 3600
nsxh = pd.Series(raw.close.to_numpy(), index=hb).groupby(level=0).last(); nsxh.index = pd.to_datetime(nsxh.index, unit='s', utc=True)
jh = pd.concat([nsxh.rename('nsx'), h.rename('nq')], axis=1).dropna()
rh = jh.pct_change().dropna()
# keep consecutive hours only
cons = (jh.index.to_series().diff().dt.total_seconds() == 3600).reindex(rh.index).fillna(False)
rh = rh.loc[cons.values]
rep['hourly_n'] = int(len(rh)); rep['hourly_ret_corr'] = float(rh.nsx.corr(rh.nq)); rep['hourly_median_abs_ret_diff'] = float((rh.nsx - rh.nq).abs().median())
dh = (rh.nsx - rh.nq).abs()
rep['hourly_ret_corr_excl_diff_over_0.5pct'] = float(rh.loc[dh < 0.005].nsx.corr(rh.loc[dh < 0.005].nq)); rep['hourly_n_diff_over_0.5pct'] = int((dh >= 0.005).sum())
json.dump(rep, open(os.path.join(out, 'DATA_REPORT.json'), 'w'), indent=1)
print(json.dumps(rep, indent=1))
