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

## Redesign and freeze (6 Oct 2026): gate v2

The v1 measure (unit distance divided by baseline units, cap 2.5) is retired. The gated measure is now
`spend_deviation = max(0, spend(plan) − spend(baseline)) / budget`: extra spend beyond the order-up-to baseline built on
the same problem, as a share of the budget (`ega.autonomy.gate_measures`). It is bounded, in money, and unaffected by
how small the baseline order is. The v1 value is still logged as `baseline_deviation` for comparison with old traces, and
`scripts/calibrate_gate.py` recomputes the v2 value exactly from the stored problem and plan of traces that predate it.

| Clean-day `spend_deviation` quantile | 50% | 75% | 90% | 95% | 99% | trips at 0.03 |
|---|---|---|---|---|---|---|
| Days 1730–1757 (140 decisions, 5 seeds) | 0.0141 | 0.0186 | 0.0233 | 0.0274 | 0.0398 | 3.6% |
| Days 1700–1727 (95 evaluated decisions) | 0.0069 | 0.0116 | 0.0203 | 0.0285 | 0.0344 | 3.2% |

The two windows now agree (v1 gave 44.1 and 5.1 at the 95th percentile). **Frozen: `gate.max_spend_deviation: 0.03`,
`gate.version: gate-v2-spend-deviation-2026-10-06`**, between the 95th and 99th percentile of both windows. The other
three caps (`max_spend` 1500, `max_days_supply` 45, `max_dispersion` 4) never tripped on clean days (95th percentiles
92.7, 28.6 and 0.12 in the clean window) and are unchanged. Pilots run before this date used v1; their hold counts
overstate what the frozen gate does. `results/*/proposed_gate_v2.json` hold the full distributions.

## Validation at the test window (6 Oct 2026)

Repeating B4 of the B1–B4 pilot (30 series, day 1830, 7 days, seeds 7 and 29) with the frozen cap did **not** reduce
holds: B4 held every day. The traces show why. The warm-up period places order-up-to orders, so the optimiser's first
decision is a catch-up that consolidates a 14-day horizon into one purchase: `spend_deviation` 0.054–0.074 on day 1830
across the eight B3 runs (B3 has no gate, so its traces show what the optimiser does when every order executes), and
0.033–0.036 on day 1730 in the calibration window. After that first order executes, the measure settles: median 0.017
(95th percentile 0.038) on later days at 1830, median 0.013–0.014 at 1730. With the cap at 0.03 and `approval_mode:
hold`, the day-1830 catch-up is held, nothing executes, the identical catch-up is proposed and held the next day, and the
run never reaches steady state (0.052–0.065 on all seven days). The calibration window's 3.6% trip rate is almost
exactly its five first days.

So the cap is a steady-state cap and the hold-release rule decides whether steady state is ever reached. The frozen value
is unchanged; the choice below is a design decision for the dissertation, not a calibration question:

1. Keep 0.03 and model approval: `approval_mode: oracle` releases a held plan after `approval_delay` days if it still
   passes the current-state constraint checks (simulated reviewers, separately labelled). Validation arm:
   `results/baseline_pilot_gate_v2_oracle_approval`.
2. Keep 0.03 and `hold`, accepting that an autonomous system which may never receive approval cannot make catch-up
   purchases; report the service cost.
3. Recalibrate including first days (about 0.06 at the 95th percentile at day 1830), which makes the deviation check
   nearly vacuous on clean evidence and shifts protection to the state certificate and the critic.
4. Change the transparent baseline to a horizon-matched order-up-to so the measure no longer scores horizon consolidation
   as deviation; this redefines the baseline the dissertation describes.

**Decision (6 Oct 2026): option 1.** The primary configuration releases held plans through simulated delayed reviewers
(`approval_mode: oracle`, `approval_delay: 1`), labelled as such in every trace; `approval_mode: hold` is reported as the
ablation. The cap stays at 0.03. "Harmful" executions are now reported split into true-constraint violations
(`violation_executions`) and distance-to-reference flags (`reference_deviations`); the two simulated-approval flags above
were the latter.

The 2-series LLM pilot repeated with the frozen cap (`results/llm_pilot_cerebras_gate_v2`) behaved as intended: B4, B8
and B10 acted on every clean day (previously one hold each) with no harmful order; its day-1800 catch-up is only
0.003 of budget because two series order a few units.

## Price gaps in M5

Days 1700–1727 are unusable for calibration. M5 has no sell price for FOODS_2_001 at CA_2, CA_4 and WI_2 on 22, 15 and 8
of days 1686–1727, although the item sold on those days. The price-coverage check hard-fails, which holds the whole
30-series decision, and B4's fill rate fell to 49–65%. Those runs are kept in `results/gate_calibration_1700_price_gap`.
