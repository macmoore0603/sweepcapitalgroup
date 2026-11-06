# What the evidence says, 2026-11-03

Every figure below was read on the primary source page, which is linked.

## How day traders fare

- **Brazil, mini-index futures** (Chague, De-Losso & Giovannetti, working paper 2019, SSRN 2020):
  - Of the 1,551 people who day traded for more than 300 days, 97% lost money.
  - 1.1% earned more than the minimum wage, and losses did not shrink with experience.
- **Taiwan, all day trades 1992-2006** (Barber, Lee, Liu & Odean, *Journal of Financial Markets* 2014):
  - About 20% are profitable in a given year, but fewer than 1% are profitable predictably.
  - The few skilled traders do persist.
- **India, F&O traders** (SEBI 2023, 2024, 2026): 89-93% lost money. Losers kept trading, and experience did not lower the losing rate.
- **EU, France, Australia CFD clients** (ESMA, AMF, ASIC): 68-89% lost money.

## Prop firms (firm-published, unaudited)

| | Evaluations passed | Funded traders paid | Went live |
|---|---|---|---|
| [Tradeify](https://tradeify.co/), Aug 2025-Jul 2026 | 17.2% (median 3 evaluations per person) | 28.5% | 3.0% |
| [Topstep](https://www.topstep.com/disclosures-notices), 2025 | 16.8% | 33.3% | 0.71% |

## Short-horizon index-futures strategies

- **Last-half-hour momentum:** the prior close-to-15:30 return predicts 15:30-16:00.
  - Strong in-sample: Gao et al., *JFE* 2018; Baltussen et al., *JFE* 2021 (NQ out-of-sample R² 3.8%, before costs).
  - The predictability disappeared over 2014-2018 and returned only in the 2020 volatility ([Rosa, *Journal of Futures Markets* 2022](https://onlinelibrary.wiley.com/doi/10.1002/fut.22375)).
  - Our October test on 14 years of NQ also failed.
- **Overnight drift, 02:00-03:00 ET** (Boyarchenko, Larsen & Whelan, *RFS* 2023): Sharpe 1.1 before costs on ES, -0.5 after the bid-ask spread. Only a buy-after-a-selloff variant survived costs.
  - Our pre-registered test on NQ failed. T5a: out-of-sample +4.0 points per trade, p 0.09, Holm p 0.18, with a negative in-sample mean. T5b (after a down day): out-of-sample +3.1, p 0.25.
  - Both were reproduced independently.
- **Pre-FOMC drift** (Lucca & Moench, *JF* 2015): disappeared right after the original sample ([Ben Dor & Rosa 2019](https://doi.org/10.3905/jfi.2019.28.4.060)). The original effect also needs an overnight hold.
- **Decay after publication** (McLean & Pontiff, *JF* 2016): about 58% of an anomaly's return disappears after it is published.
- **Common MNQ signals:** 14 price/volume signal families on MNQ, 2021-2025, all failed out-of-sample walk-forward tests after a 2-point round-trip cost ([arXiv 2605.04004](https://arxiv.org/pdf/2605.04004v2), preprint).

## Longer horizons

- **Trend following:** the best-documented futures strategy (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen, 1880-2016).
  - It needs positions held about a month and dozens of diversified markets. A single market's Sharpe is about 0.4.
  - The SG Trend Index made 3.7% a year over the 10 years to December 2025.
  - It cannot be run inside an intraday prop-firm account.

## Sizing

- **Kelly:** betting half of the Kelly fraction keeps three quarters of the growth and cuts the chance of ever halving from 1 in 2 to 1 in 8 (Thorp 2006).
- **Overestimated edge:** betting above Kelly when the true edge is smaller leads to ruin.
- **A small edge in a small cushion:** survival depends on size first.
