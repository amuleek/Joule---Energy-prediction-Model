# Joule research: what is (and isn't) forecastable

Every claim below comes from scripts in this folder and can be re-run.
All tests are out-of-sample: models only see data available at the time.

## Rules we follow
1. **Baseline first.** Every model is scored against "price stays at today's settle".
   A model that can't beat it doesn't ship.
2. **No look-ahead.** Weekly EIA data enters on its release date, CFTC data on its Friday
   release, gaps are forward-filled only, training data is purged around the test window.
3. **Roll-adjusted prices.** Continuous front-month series jump when contracts roll
   (RBOB's spring/autumn grade switch is large and seasonal). Signals that only work on the
   unadjusted series are artifacts.
4. **Discovery / confirmation split.** With hundreds of candidate signals, ~5% look
   significant by chance. A signal must hold in 2006-2015 *and* 2016+ with the same sign.
5. **Paper-track before promoting.** Anything chosen after looking at the data is
   logged on new data (`signal_log.csv`) before it can affect a forecast.

## Findings (Nov 2026)

| Question | Answer | Script |
|---|---|---|
| Does any model beat "no change" on price error (crude, RBOB, ULSD; 1/4/7 days)? | **No.** Ridge and LightGBM on 55-74 features: 1-7% worse. | `backtest.py` |
| Was the RBOB 53-55% direction edge real? | **No.** It came from contract-roll jumps; roll-adjusted it is 46-49%. | `curve.py`, `backtest.py --data dataset_rolladj.csv` |
| Does the futures curve (contango/backwardation) help daily direction? | No. | `backtest.py --data dataset_curve.csv` |
| Do OVX or CFTC positioning help? | Not on price error (all models still 1.5-11% worse than no-change). Crude 7-day ridge reaches 52.7% direction, the same effect as the composite. One crude composite ("products lead crude") works 2016+ (54-55% at 4-7 days) but **failed 2010-2015 (48%)**, so it is paper-tracked only. | `signal_scan.py`, `crude_composite.py`, `track_signals.py` |
| Can we forecast a reliable price **range**? | **Yes.** EWMA volatility + empirical quantiles: 80% bands cover 79-81%, 95% bands 94-95% (2014-2026). | `volatility.py` |
| Does OVX improve the ranges? | **Yes, modestly.** A 50/50 EWMA + OVX blend beats EWMA in all 9 product/horizon cells (interval score -2 to -4% at 80%, -4 to -8% at 95%). | `volatility.py --data dataset_plus.csv` |

**Live model** (`../baseline_forecast.py`): centre = last settle, 80% / 95% ranges from
EWMA + OVX volatility. `FORECAST_MODE=legacy` restores the old stack.

## Most promising next data
Rack / retail / supplier prices (they lag futures by days, so they are likely
forecastable from futures), then options-implied vol for gasoline and diesel.

## Run
```bash
pip install -r research/requirements.txt
python research/build_dataset.py      # needs EIA_API_KEY in ../.env for inventories + curve
python research/backtest.py --data research/data/dataset_plus.csv --tag plus
python research/volatility.py --data research/data/dataset_plus.csv
python research/signal_scan.py
python research/crude_composite.py
```
