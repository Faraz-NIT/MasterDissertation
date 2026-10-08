"""Meaningful isolation checks for the bounded FreshRetailNet benchmark."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/freshretailnet/forecast_study.py"
SPEC = importlib.util.spec_from_file_location("frn_forecast", SOURCE)
forecast = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(forecast)


def panel(days=42):
    rows = []
    for series_index, series in enumerate(("A", "B")):
        for day in range(days):
            hourly = np.zeros(24)
            hourly[6:22] = np.arange(1, 17) / 100 + series_index / 10 + (day % 7) / 100
            status = np.zeros(24, dtype=int)
            if day % 5 == 0:
                status[10:12] = 1
                hourly[10:12] = 0
            rows.append({"series_id": series, "day_index": day,
                "dt": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=day)).strftime("%Y-%m-%d"),
                "sale_amount": hourly.sum(), "hours_sale": hourly,
                "hours_stock_status": status, "stock_hour6_22_cnt": int(status[6:22].sum()),
                "discount": 0.9, "avg_temperature": 15})
    return forecast.validate_frame(pd.DataFrame(rows), "test")


def test_unfrozen_protocol_opens_no_data(tmp_path, monkeypatch):
    (tmp_path / "protocol.json").write_text(json.dumps({"status": "draft"}))
    reads = []
    monkeypatch.setattr(pd, "read_parquet", lambda path: reads.append(path))
    with pytest.raises(RuntimeError, match="not frozen"):
        forecast.run(tmp_path)
    assert reads == []


def test_recovery_never_changes_unflagged_hours_or_raw_sales():
    source = panel(35)
    model = forecast.Recovery(["A", "B"]).fit(source)
    recovered = model.natural_panel(source)
    assert np.array_equal(source.sale_amount, recovered.sale_amount)
    for row in recovered.itertuples(index=False):
        original = np.asarray(row.hours_sale)
        flagged = np.asarray(row.hours_stock_status) == 1
        for method in ("profile", "gbm"):
            value = np.asarray(getattr(row, f"{method}_recovered_hours_sale"))
            assert np.array_equal(value[~flagged], original[~flagged])
            assert np.all(value[flagged] >= original[flagged])


def test_recursive_predictions_ignore_future_truth_masks_weather(tmp_path):
    source = panel(42)
    past = source.loc[source.day_index.lt(35)]
    future = source.loc[source.day_index.ge(35)]
    recovered = forecast.Recovery(["A", "B"]).fit(past).natural_panel(past)
    models = forecast.fit_forecasts(recovered, ["A", "B"], tmp_path)
    distorted = forecast.scramble_future(future, 35)
    for method, (model, column) in models.items():
        first = forecast.predict_daily(model, recovered, future, ["A", "B"], column,
                                       seasonal=method == "seasonal_naive_raw")
        second = forecast.predict_daily(model, recovered, distorted, ["A", "B"], column,
                                        seasonal=method == "seasonal_naive_raw")
        assert len(first) == 14
        assert np.array_equal(first.prediction, second.prediction)


def test_artificial_masks_only_use_stocked_heldout_days():
    source = panel(42)
    past = source.loc[source.day_index.lt(35)]
    future = source.loc[source.day_index.ge(35)]
    model = forecast.Recovery(["A", "B"]).fit(past)
    rows, _ = forecast.mask_validation(model, future, 35)
    records = pd.DataFrame(rows)
    stocked = set(zip(future.loc[future.fully_stocked].series_id,
                      future.loc[future.fully_stocked].day_index))
    assert set(zip(records.series_id, records.day_index)) <= stocked
    assert records.hour.between(6, 21).all()
    assert set(records.mask_duration) == {2, 4, 8}
    repeated, _ = forecast.mask_validation(model, future, 35)
    assert rows == repeated


def test_artificial_mask_predictions_do_not_use_heldout_sales_totals():
    source = panel(42)
    past = source.loc[source.day_index.lt(35)]
    future = source.loc[source.day_index.ge(35)].copy()
    model = forecast.Recovery(["A", "B"]).fit(past)
    original, _ = forecast.mask_validation(model, future, 35)
    # Preserve availability and calendar while changing all hidden truths and
    # the corresponding daily aggregate; both are forbidden predictor inputs.
    changed = future.copy(deep=True)
    for i in changed.index:
        changed.at[i, "hours_sale"] = np.asarray(changed.at[i, "hours_sale"]) + 1000
    changed["sale_amount"] += 24000
    distorted, _ = forecast.mask_validation(model, changed, 35)
    assert [row["prediction"] for row in original] == [row["prediction"] for row in distorted]
    assert [row["target"] for row in original] != [row["target"] for row in distorted]
