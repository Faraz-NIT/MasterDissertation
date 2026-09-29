# Gate calibration

The autonomy gate's deviation cap (`gate.max_deviation`, default 2.5) was an uncalibrated default. In every M5 pilot
it was the only cap that fired on clean evidence, so it caused most holds.

## Method

1. Run B4 on the normal scenario with the cap disabled: `ega run --config configs/gate_calibration.yaml`.
   The window, decision days 1730–1757 with warm-up from day 1716, is disjoint from every test window (the earliest
   test warm-up starts at day 1786). Seeds 0–4, 30 series, 140 decisions.
2. `python scripts/calibrate_gate.py` reads the gate inputs logged on every evaluated decision and reports their
   quantiles. A cap at the 95th percentile trips on about 5% of clean-evidence days, leaving faults to the state
   certificate and the critic.

## Result (29 Sep 2026)

| Clean-day deviation quantile | 50% | 75% | 90% | 95% | 99% |
|---|---|---|---|---|---|
| Days 1730–1757 | 11.0 | 26.3 | 39.1 | 44.1 | 52.9 |

The default cap of 2.5 would hold on about 90% of clean days. The 95th-percentile cap, 44, barely constrains anything.
An earlier window (days 1700–1727) gave a 95th percentile of 5.1. The measure divides by the size of the baseline
order, so small baseline orders inflate it and the distribution is unstable. **Recommendation: redesign the measure
(for example, extra spend beyond the baseline as a share of the budget) before calibrating and freezing it.** The cap
has not been changed in any config yet.

## Price gaps in M5

Days 1700–1727 are unusable for calibration. M5 has no sell price for FOODS_2_001 at CA_2, CA_4 and WI_2 on 22, 15 and 8
of days 1686–1727, although the item sold on those days. The price-coverage check hard-fails, which holds the whole
30-series decision, and B4's fill rate fell to 49–65%. Those runs are kept in `results/gate_calibration_1700_price_gap`.
