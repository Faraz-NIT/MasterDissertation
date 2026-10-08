#!/usr/bin/env python3
"""Frozen, past-only FreshRetailNet recovery and point-forecast benchmark.

Observed sales during organic stockouts are a censored proxy: this program never
labels their unobserved demand as truth. Recovery accuracy is scored exclusively
on deliberately hidden hours of held-out, fully stocked days. Final forecasting
uses one untouched seven-day release split after validation selection is saved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HOURS = np.arange(6, 22)
FOLDS = (62, 69, 76, 83)
FORECAST_METHODS = (
    "seasonal_naive_raw", "lightgbm_raw", "lightgbm_profile_recovered",
    "lightgbm_gbm_recovered",
)
RECOVERY_METHODS = ("raw_zero", "profile", "gbm")
CONTEXT_FIELDS = ("discount", "holiday_flag", "activity_flag", "precpt",
                  "avg_temperature", "avg_humidity", "avg_wind_level")
DAILY_FEATURES = ("lag1", "lag7", "lag14", "lag28", "mean7", "mean28",
                  "std7", "series_index", "weekday")
HOURLY_FEATURES = ("series_index", "hour", "weekday", "series_hour_profile",
                   "series_operating_hour_mean", "global_hour_profile")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    pending.replace(path)


def clean_number(value):
    return float(value) if np.isfinite(value) else None


def metric(y, predicted):
    y = np.asarray(y, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if not len(y):
        return {"n": 0, "mae": None, "rmse": None, "norm_mae": None,
                "norm_rmse": None, "wape": None, "bias": None,
                "relative_bias": None, "target_sum": 0.0}
    error = predicted - y
    scale = np.mean(np.abs(y))
    total = np.sum(np.abs(y))
    mae = np.mean(np.abs(error))
    rmse = np.sqrt(np.mean(error ** 2))
    return {"n": len(y), "mae": clean_number(mae), "rmse": clean_number(rmse),
            "norm_mae": clean_number(mae / scale) if scale > 0 else None,
            "norm_rmse": clean_number(rmse / scale) if scale > 0 else None,
            "wape": clean_number(np.sum(np.abs(error)) / total) if total > 0 else None,
            "bias": clean_number(np.mean(error)),
            "relative_bias": clean_number(np.sum(error) / total) if total > 0 else None,
            "target_sum": float(np.sum(y))}


def validate_frame(frame, name):
    required = {"series_id", "day_index", "dt", "sale_amount", "hours_sale",
                "hours_stock_status", "stock_hour6_22_cnt"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} misses {sorted(missing)}")
    frame = frame.copy().sort_values(["series_id", "day_index"]).reset_index(drop=True)
    if frame.duplicated(["series_id", "day_index"]).any():
        raise ValueError(f"{name} contains repeated series/day")
    sales = np.stack(frame.hours_sale.map(lambda x: np.asarray(x, dtype=float)))
    stock = np.stack(frame.hours_stock_status.map(lambda x: np.asarray(x, dtype=int)))
    if sales.shape[1] != 24 or stock.shape[1] != 24:
        raise ValueError("Expected complete 24-hour vectors")
    if not np.isfinite(sales).all() or (sales < 0).any():
        raise ValueError("Hourly sales must be finite and non-negative")
    if not np.isin(stock, [0, 1]).all():
        raise ValueError("Stock status must be 0 (available) or 1 (out of stock)")
    frame["weekday"] = pd.to_datetime(frame.dt).dt.dayofweek.astype(int)
    frame["fully_stocked"] = frame.stock_hour6_22_cnt.eq(0)
    counts = stock[:, HOURS].sum(axis=1)
    if not np.array_equal(counts, frame.stock_hour6_22_cnt.to_numpy(dtype=int)):
        raise ValueError("Stockout count disagrees with flags at operating hours 6:22")
    return frame


class Recovery:
    """Models see exclusively unflagged historical operating-hour sales."""

    def __init__(self, series_order, alpha=14.0):
        self.series_order = list(series_order)
        self.index = {series: i for i, series in enumerate(self.series_order)}
        self.alpha = alpha
        self.model = None

    def fit(self, past):
        sums = np.zeros((len(self.series_order), 24))
        counts = np.zeros_like(sums)
        for row in past.itertuples(index=False):
            i = self.index[row.series_id]
            sale = np.asarray(row.hours_sale, dtype=float)
            stock = np.asarray(row.hours_stock_status, dtype=int)
            available = HOURS[stock[HOURS] == 0]
            sums[i, available] += sale[available]
            counts[i, available] += 1
        global_count = counts.sum(axis=0)
        self.global_profile = np.divide(sums.sum(axis=0), global_count,
                                        out=np.zeros(24), where=global_count > 0)
        self.profile = (sums + self.alpha * self.global_profile[None, :]) / (counts + self.alpha)
        self.series_mean = np.divide(sums[:, HOURS].sum(axis=1), counts[:, HOURS].sum(axis=1),
                                     out=np.zeros(len(self.series_order)),
                                     where=counts[:, HOURS].sum(axis=1) > 0)
        self.counts = counts
        features, targets = [], []
        for row in past.itertuples(index=False):
            sale = np.asarray(row.hours_sale, dtype=float)
            stock = np.asarray(row.hours_stock_status, dtype=int)
            for hour in HOURS[stock[HOURS] == 0]:
                features.append(self.feature(row.series_id, int(hour), row.weekday))
                targets.append(sale[hour])
        self.model = lgb.LGBMRegressor(
            objective="regression_l1", n_estimators=150, max_depth=5,
            num_leaves=20, min_child_samples=20, learning_rate=0.05,
            random_state=42, n_jobs=1, verbosity=-1, deterministic=True,
            force_col_wise=True,
        )
        self.model.fit(pd.DataFrame(features, columns=HOURLY_FEATURES), targets)
        self.available_hour_training_count = len(targets)
        self.training_last_day = int(past.day_index.max())
        return self

    def feature(self, series, hour, weekday):
        i = self.index[series]
        return [i, hour, weekday, self.profile[i, hour], self.series_mean[i],
                self.global_profile[hour]]

    def predict(self, series, hours, weekday, method):
        if method == "raw_zero":
            return np.zeros(len(hours))
        if method == "profile":
            return self.profile[self.index[series], hours]
        features = [self.feature(series, int(hour), weekday) for hour in hours]
        return np.maximum(0, self.model.predict(pd.DataFrame(features, columns=HOURLY_FEATURES)))

    def natural_panel(self, past):
        recovered = past.copy()
        for method in ("profile", "gbm"):
            daily, hourly = [], []
            for row in past.itertuples(index=False):
                values = np.asarray(row.hours_sale, dtype=float).copy()
                flagged = HOURS[np.asarray(row.hours_stock_status)[HOURS] == 1]
                if len(flagged):
                    values[flagged] = np.maximum(values[flagged], self.predict(
                        row.series_id, flagged, row.weekday, method))
                daily.append(float(row.sale_amount + np.sum(values - np.asarray(row.hours_sale))))
                hourly.append(values.tolist())
            recovered[f"{method}_recovered_sale_amount"] = daily
            recovered[f"{method}_recovered_hours_sale"] = hourly
        return recovered

    def save(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.model.booster_.save_model(str(path / "hourly_lightgbm.txt"))
        json_write(path / "hourly_profile.json", {
            "series_order": self.series_order, "alpha": self.alpha,
            "operating_hours": HOURS.tolist(), "profile": self.profile.tolist(),
            "global_profile": self.global_profile.tolist(),
            "series_mean": self.series_mean.tolist(), "counts": self.counts.tolist(),
            "training_last_day": self.training_last_day,
            "available_hour_training_count": self.available_hour_training_count,
        })


def mask_validation(recovery, held, fold):
    rows, daily_rows = [], []
    for row in held.loc[held.fully_stocked].itertuples(index=False):
        observed = np.asarray(row.hours_sale, dtype=float)
        for duration in (2, 4, 8):
            digest = hashlib.sha256(f"FRN-mask-v1|{fold}|{row.series_id}|{row.dt}|{duration}".encode()).digest()
            start = 6 + int.from_bytes(digest[:8], "big") % (16 - duration + 1)
            hours = np.arange(start, start + duration)
            target = observed[hours]
            for method in RECOVERY_METHODS:
                predicted = recovery.predict(row.series_id, hours, row.weekday, method)
                for hour, actual, prediction in zip(hours, target, predicted):
                    rows.append({"fold": fold, "train_end_exclusive": fold,
                        "series_id": row.series_id, "dt": row.dt, "day_index": row.day_index,
                        "mask_duration": duration, "mask_start": start, "hour": int(hour),
                        "method": method, "target": float(actual), "prediction": float(prediction),
                        "target_kind": "artificially_hidden_observed_in_stock_sales"})
                reconstructed = row.sale_amount - target.sum() + predicted.sum()
                daily_rows.append({"fold": fold, "series_id": row.series_id, "dt": row.dt,
                    "day_index": row.day_index, "mask_duration": duration, "mask_start": start,
                    "method": method, "observed_daily": float(row.sale_amount),
                    "reconstructed_daily": float(reconstructed),
                    "error": float(reconstructed - row.sale_amount)})
    return rows, daily_rows


def daily_feature(history, series_index, weekday):
    history = np.asarray(history, dtype=float)
    if len(history) < 28:
        raise ValueError("Daily forecasting requires at least 28 prior observations")
    return [history[-1], history[-7], history[-14], history[-28],
            np.mean(history[-7:]), np.mean(history[-28:]), np.std(history[-7:]),
            series_index, weekday]


def histories(past, series_order, column):
    return {series: past.loc[past.series_id.eq(series)].sort_values("day_index")[column]
            .to_numpy(dtype=float) for series in series_order}


def fit_daily(past, series_order, column):
    features, targets = [], []
    for i, series in enumerate(series_order):
        subset = past.loc[past.series_id.eq(series)].sort_values("day_index")
        values = subset[column].to_numpy(dtype=float)
        weekdays = subset.weekday.to_numpy(dtype=int)
        for t in range(28, len(values)):
            features.append(daily_feature(values[:t], i, weekdays[t]))
            targets.append(values[t])
    model = lgb.LGBMRegressor(objective="regression_l1", n_estimators=150,
        max_depth=5, num_leaves=20, min_child_samples=10, learning_rate=0.05,
        random_state=42, n_jobs=1, verbosity=-1, deterministic=True, force_col_wise=True)
    model.fit(pd.DataFrame(features, columns=DAILY_FEATURES), targets)
    return model


def predict_daily(model, past, future_metadata, series_order, column, seasonal=False):
    # Only these metadata fields are admitted: no sales, stock flags or context.
    metadata = future_metadata[["series_id", "day_index", "dt"]].copy()
    metadata["weekday"] = pd.to_datetime(metadata.dt).dt.dayofweek.astype(int)
    series_index = {series: i for i, series in enumerate(series_order)}
    history = histories(past, series_order, column)
    result = []
    for day, daily in metadata.groupby("day_index", sort=True):
        daily = daily.sort_values("series_id")
        if seasonal:
            predicted = np.asarray([history[series][-7] for series in daily.series_id])
        else:
            features = [daily_feature(history[row.series_id], series_index[row.series_id], row.weekday)
                        for row in daily.itertuples(index=False)]
            predicted = np.maximum(0, model.predict(pd.DataFrame(features, columns=DAILY_FEATURES)))
        for row, value in zip(daily.itertuples(index=False), predicted):
            result.append({"series_id": row.series_id, "day_index": int(day),
                           "dt": row.dt, "prediction": float(value)})
            history[row.series_id] = np.append(history[row.series_id], value)
    return pd.DataFrame(result)


def fit_forecasts(past, series_order, model_dir):
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    models = {}
    columns = {
        "seasonal_naive_raw": "sale_amount", "lightgbm_raw": "sale_amount",
        "lightgbm_profile_recovered": "profile_recovered_sale_amount",
        "lightgbm_gbm_recovered": "gbm_recovered_sale_amount",
    }
    for method, column in columns.items():
        model = None if method == "seasonal_naive_raw" else fit_daily(past, series_order, column)
        models[method] = (model, column)
        if model is not None:
            model.booster_.save_model(str(model_dir / f"{method}.txt"))
    return models


def forecast_frames(models, past, future, series_order, fold, partition):
    rows = []
    for method, (model, column) in models.items():
        predicted = predict_daily(model, past, future, series_order, column,
                                  seasonal=method == "seasonal_naive_raw")
        predicted = predicted.merge(future[["series_id", "day_index", "sale_amount", "fully_stocked"]],
                                    on=["series_id", "day_index"], validate="one_to_one")
        predicted = predicted.rename(columns={"sale_amount": "observed_sales"})
        predicted["method"], predicted["fold"] = method, fold
        predicted["train_end_exclusive"], predicted["partition"] = fold, partition
        rows.append(predicted)
    return pd.concat(rows, ignore_index=True)


def forecasting_metrics(predictions):
    rows = []
    for partition, group in predictions.groupby("partition"):
        for fold in ["pooled"] + sorted(group.fold.unique().tolist()):
            fold_group = group if fold == "pooled" else group.loc[group.fold.eq(fold)]
            for method, method_group in fold_group.groupby("method"):
                for target_kind in ("observed_daily_proxy", "fully_in_stock_daily_sales"):
                    scored = method_group if target_kind == "observed_daily_proxy" else method_group.loc[method_group.fully_stocked]
                    rows.append({"partition": partition, "fold": fold, "method": method,
                                 "target_kind": target_kind, "series_id": "ALL",
                                 **metric(scored.observed_sales, scored.prediction)})
                    if fold == "pooled":
                        for series in sorted(method_group.series_id.unique()):
                            one = scored.loc[scored.series_id.eq(series)]
                            rows.append({"partition": partition, "fold": fold, "method": method,
                                "target_kind": target_kind, "series_id": series,
                                **metric(one.observed_sales, one.prediction)})
    return pd.DataFrame(rows)


def recovery_metrics(predictions, daily):
    rows, daily_rows = [], []
    for duration in ["all", 2, 4, 8]:
        hourly = predictions if duration == "all" else predictions.loc[predictions.mask_duration.eq(duration)]
        days = daily if duration == "all" else daily.loc[daily.mask_duration.eq(duration)]
        for method, group in hourly.groupby("method"):
            rows.append({"mask_duration": duration, "method": method, "series_id": "ALL",
                         **metric(group.target, group.prediction)})
            for series, one in group.groupby("series_id"):
                rows.append({"mask_duration": duration, "method": method, "series_id": series,
                             **metric(one.target, one.prediction)})
        for method, group in days.groupby("method"):
            daily_rows.append({"mask_duration": duration, "method": method, "series_id": "ALL",
                               **metric(group.observed_daily, group.reconstructed_daily)})
            for series, one in group.groupby("series_id"):
                daily_rows.append({"mask_duration": duration, "method": method, "series_id": series,
                                   **metric(one.observed_daily, one.reconstructed_daily)})
    return pd.DataFrame(rows), pd.DataFrame(daily_rows)


def feature_hash(past):
    normalized = []
    for row in past.sort_values(["series_id", "day_index"]).itertuples(index=False):
        normalized.append([row.series_id, int(row.day_index), row.dt, float(row.sale_amount),
                           list(map(float, row.hours_sale)), list(map(int, row.hours_stock_status))])
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


def scramble_future(frame, boundary):
    perturbed = frame.copy(deep=True)
    selected = perturbed.day_index.ge(boundary)
    perturbed.loc[selected, "sale_amount"] = 987654.0
    for i in perturbed.index[selected]:
        perturbed.at[i, "hours_sale"] = np.repeat(123456.0, 24)
        perturbed.at[i, "hours_stock_status"] = np.ones(24, dtype=int)
    perturbed.loc[selected, "stock_hour6_22_cnt"] = 16
    for column in CONTEXT_FIELDS:
        if column in perturbed:
            perturbed.loc[selected, column] = -123456.0
    return perturbed


def run(root):
    root = Path(root).resolve()
    protocol_path = root / "protocol.json"
    if not protocol_path.exists():
        raise RuntimeError("Study protocol is not present: evaluation data stays unopened")
    protocol = json.loads(protocol_path.read_text())
    if str(protocol.get("status", "")).lower() != "frozen":
        raise RuntimeError("Study protocol is not frozen: evaluation data stays unopened")
    out = root / "forecast"
    if (out / "completion_receipt.json").exists():
        raise RuntimeError("Completed study must not be overwritten")
    out.mkdir(parents=True, exist_ok=True)
    events = []

    def event(action, **details):
        record = {"timestamp_utc": utc_now(), "action": action, **details}
        events.append(record)
        with (out / "execution_events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        print(json.dumps(record), flush=True)

    config = {"study": "FreshRetailNet F1 recovery and F2 forecasting", "started_utc": utc_now(),
        "protocol_sha256": sha256(protocol_path), "source_sha256": sha256(__file__),
        "fold_train_end_exclusive": list(FOLDS), "horizon_days": 7,
        "operating_hour_slice": [6, 22], "stockout_flag": 1,
        "mask_durations": [2, 4, 8], "mask_selection": "SHA256 deterministic contiguous windows",
        "recovery_methods": list(RECOVERY_METHODS), "forecast_methods": list(FORECAST_METHODS),
        "profile_shrinkage_pseudo_days": 14, "lightgbm_n_estimators": 150,
        "lightgbm_seed": 42, "lightgbm_n_jobs": 1,
        "hourly_features": list(HOURLY_FEATURES), "daily_features": list(DAILY_FEATURES),
        "forecast_strategy": "static-origin seven-day recursive point forecasts",
        "future_covariates": "only date/weekday and series identifier; no released targets, masks, weather or promotion",
        "natural_recovery": "max(observed,prediction) at flagged operating hours; other hours unchanged",
        "limitations": ["No natural latent-demand ground truth exists in the released data",
            "Artificially masked in-stock hours are not organic-stockout truth",
            "Observed daily sales are a censored proxy; fully in-stock scoring is conditional",
            "These compact baselines do not reproduce official DeepAR or TFT"],
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "lightgbm": lgb.__version__}}
    json_write(out / "config.json", config)
    event("load_training_only", path=str(root / "data/selected_train.parquet"))
    train_path = root / "data/selected_train.parquet"
    train = validate_frame(pd.read_parquet(train_path), "train")
    if set(train.day_index.unique()) != set(range(90)):
        raise ValueError("Training split must have indices 0 through 89")
    series_order = sorted(train.series_id.unique().tolist())
    if len(series_order) != 30 or len(train) != 2700:
        raise ValueError("Frozen selected panel must have 30 complete 90-day series")
    train_hash = sha256(train_path)
    fold_predictions, all_masks, all_mask_days, leakage = [], [], [], []
    for boundary in FOLDS:
        event("fit_fold", train_end_exclusive=boundary)
        past = train.loc[train.day_index.lt(boundary)].copy()
        held = train.loc[train.day_index.ge(boundary) & train.day_index.lt(boundary + 7)].copy()
        model_dir = out / "models" / f"fold_{boundary}"
        recovery = Recovery(series_order).fit(past)
        recovery.save(model_dir)
        masks, masked_days = mask_validation(recovery, held, boundary)
        all_masks.extend(masks)
        all_mask_days.extend(masked_days)
        recovered = recovery.natural_panel(past)
        recovered.to_parquet(out / f"recovered_training_fold_{boundary}.parquet", index=False)
        models = fit_forecasts(recovered, series_order, model_dir)
        predictions = forecast_frames(models, recovered, held, series_order, boundary, "validation")
        fold_predictions.append(predictions)
        perturbed = scramble_future(train, boundary)
        assert feature_hash(past) == feature_hash(perturbed.loc[perturbed.day_index.lt(boundary)])
        for method, (model, column) in models.items():
            expected = predict_daily(model, recovered, held, series_order, column,
                                     seasonal=method == "seasonal_naive_raw")
            scrambled = predict_daily(model, recovered,
                perturbed.loc[perturbed.day_index.ge(boundary) & perturbed.day_index.lt(boundary + 7)],
                series_order, column, seasonal=method == "seasonal_naive_raw")
            assert np.array_equal(expected.prediction, scrambled.prediction)
            leakage.append({"partition": "validation", "train_end_exclusive": boundary,
                "method": method, "scrambled_fields": ["sale_amount", "hours_sale", "hours_stock_status",
                    "stock_hour6_22_cnt", *CONTEXT_FIELDS], "training_feature_hash_unchanged": True,
                "recursive_predictions_bitwise_equal": True,
                "n_predictions": len(expected)})
        event("fold_complete", train_end_exclusive=boundary,
              artificial_mask_hour_records=len(masks), forecast_records=len(predictions))
    validation = pd.concat(fold_predictions, ignore_index=True)
    mask_predictions, mask_days = pd.DataFrame(all_masks), pd.DataFrame(all_mask_days)
    if mask_predictions.empty:
        raise RuntimeError("No fully-stocked validation days: selection cannot be scored")
    forecast_metrics = forecasting_metrics(validation)
    mask_metrics, mask_daily_metrics = recovery_metrics(mask_predictions, mask_days)
    validation.to_csv(out / "forecasts_validation.csv", index=False)
    mask_predictions.to_csv(out / "artificial_mask_predictions.csv", index=False)
    mask_days.to_csv(out / "artificial_mask_daily_reconstruction.csv", index=False)
    mask_metrics.to_csv(out / "recovery_hour_metrics.csv", index=False)
    mask_daily_metrics.to_csv(out / "recovery_daily_metrics.csv", index=False)
    forecast_metrics.to_csv(out / "forecast_metrics_validation.csv", index=False)
    recovery_scores = mask_metrics.loc[(mask_metrics.series_id == "ALL") & (mask_metrics.mask_duration == "all")]
    recovery_winner = recovery_scores.sort_values(["mae", "method"]).iloc[0]
    candidates = forecast_metrics.loc[(forecast_metrics.series_id == "ALL") &
        (forecast_metrics.fold == "pooled") & (forecast_metrics.target_kind == "fully_in_stock_daily_sales")]
    if not candidates.n.gt(0).all() or candidates.wape.isna().any():
        raise RuntimeError("Fully in-stock validation WAPE is unavailable; no evaluation selection made")
    forecast_winner = candidates.sort_values(["wape", "method"]).iloc[0]
    selection = {"status": "frozen", "frozen_utc": utc_now(), "eval_data_opened": False,
        "recovery": {"method": recovery_winner.method, "criterion": "pooled artificial-mask hourly MAE",
            "score": float(recovery_winner.mae), "candidates": recovery_scores[["method", "mae", "wape", "n"]].to_dict("records")},
        "forecast": {"method": forecast_winner.method, "criterion": "pooled validation fully-in-stock daily WAPE",
            "score": float(forecast_winner.wape), "candidates": candidates[["method", "wape", "n"]].to_dict("records")},
        "training_sha256": train_hash,
        "validation_forecasts_sha256": sha256(out / "forecasts_validation.csv"),
        "mask_predictions_sha256": sha256(out / "artificial_mask_predictions.csv"),
        "protocol_sha256": config["protocol_sha256"], "source_sha256": config["source_sha256"]}
    json_write(out / "selection_receipt.json", selection)
    selection_hash = sha256(out / "selection_receipt.json")
    event("validation_selection_frozen", selection_sha256=selection_hash,
          recovery_method=selection["recovery"]["method"], forecast_method=selection["forecast"]["method"])
    final_dir = out / "models" / "final_90_days"
    recovery = Recovery(series_order).fit(train)
    recovery.save(final_dir)
    recovered = recovery.natural_panel(train)
    selected_recovery = selection["recovery"]["method"]
    selected_column = "sale_amount" if selected_recovery == "raw_zero" else f"{selected_recovery}_recovered_sale_amount"
    recovered["selected_recovered_sale_amount"] = recovered[selected_column]
    recovered["selected_recovery_method"] = selected_recovery
    recovered.to_parquet(out / "final_recovered_train_panel.parquet", index=False)
    models = fit_forecasts(recovered, series_order, final_dir)
    event("final_models_fit_training_only", latest_training_day=89)
    # The coordinator unseals and prepares the official release split only
    # after observing the immutable validation-selection receipt above.
    eval_path = root / "data/selected_eval.parquet"
    waiting_started = time.monotonic()
    event("waiting_for_sealed_evaluation_preparation", maximum_wait_seconds=60,
          selection_sha256=selection_hash)
    while not eval_path.exists():
        if time.monotonic() - waiting_started >= 60:
            raise RuntimeError("Evaluation preparation did not finish within the bounded 60-second wait")
        time.sleep(0.2)
    event("evaluation_preparation_ready", wait_seconds=time.monotonic() - waiting_started)
    # This is deliberately the sole read of the release evaluation split.
    event("open_final_evaluation_once", selection_sha256=selection_hash,
          path=str(root / "data/selected_eval.parquet"))
    future = validate_frame(pd.read_parquet(eval_path), "eval")
    if set(future.day_index.unique()) != set(range(90, 97)) or len(future) != 210:
        raise ValueError("Evaluation must be seven complete days at indices 90 through 96")
    if sorted(future.series_id.unique().tolist()) != series_order:
        raise ValueError("Evaluation series do not match frozen training selection")
    evaluated = forecast_frames(models, recovered, future, series_order, 90, "eval")
    evaluated.to_csv(out / "forecasts_eval.csv", index=False)
    combined_metrics = forecasting_metrics(pd.concat([validation, evaluated], ignore_index=True))
    combined_metrics.to_csv(out / "forecast_metrics.csv", index=False)
    combined_metrics.loc[combined_metrics.partition.eq("eval")].to_csv(out / "forecast_metrics_eval.csv", index=False)
    scrambled_future = scramble_future(future, 90)
    for method, (model, column) in models.items():
        expected = predict_daily(model, recovered, future, series_order, column,
                                 seasonal=method == "seasonal_naive_raw")
        scrambled = predict_daily(model, recovered, scrambled_future, series_order, column,
                                  seasonal=method == "seasonal_naive_raw")
        assert np.array_equal(expected.prediction, scrambled.prediction)
        leakage.append({"partition": "eval", "train_end_exclusive": 90, "method": method,
            "scrambled_fields": ["sale_amount", "hours_sale", "hours_stock_status", "stock_hour6_22_cnt", *CONTEXT_FIELDS],
            "recursive_predictions_bitwise_equal": True, "n_predictions": len(expected),
            "selection_receipt_sha256_unchanged": sha256(out / "selection_receipt.json") == selection_hash})
    assert sha256(out / "selection_receipt.json") == selection_hash
    leakage_receipt = {"status": "passed", "checks": leakage,
        "final_eval_reads": 1, "holdout_target_or_context_feature_use": False,
        "validation_prefix_only": True, "feature_whitelist": list(DAILY_FEATURES),
        "training_last_day": 89, "evaluation_first_day": 90}
    json_write(out / "leakage_audit.json", leakage_receipt)
    summary = {"status": "completed", "completed_utc": utc_now(),
        "series_count": len(series_order), "training_rows": len(train), "eval_rows": len(future),
        "validation_prediction_rows": len(validation), "eval_prediction_rows": len(evaluated),
        "artificial_mask_hour_records": len(mask_predictions),
        "selection": selection, "leakage_audit": leakage_receipt,
        "eval_metrics": combined_metrics.loc[(combined_metrics.partition == "eval") &
            (combined_metrics.series_id == "ALL") & (combined_metrics.fold == "pooled")].to_dict("records"),
        "sales_units": "publisher globally normalized sales; not monetary costs or physical SKU units",
        "natural_recovery_added_sales": {method: float(np.sum(recovered[f"{method}_recovered_sale_amount"] - recovered.sale_amount))
                                          for method in ("profile", "gbm")},
        "observed_daily_hourly_discrepancy_max": float(np.max(np.abs(train.sale_amount.to_numpy() -
                                          np.stack(train.hours_sale).sum(axis=1)))),
        "limitations": config["limitations"]}
    json_write(out / "summary.json", summary)
    event("study_completed", eval_prediction_rows=len(evaluated), leakage_checks=len(leakage))
    files = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "completion_receipt.json":
            files.append({"path": str(path.relative_to(out)), "bytes": path.stat().st_size,
                          "sha256": sha256(path)})
    json_write(out / "completion_receipt.json", {"status": "completed", "completed_utc": utc_now(),
        "inputs": {"train_sha256": train_hash, "eval_sha256": sha256(eval_path),
                   "protocol_sha256": config["protocol_sha256"]},
        "selection_receipt_sha256": selection_hash, "files": files})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="results/freshretailnet")
    args = parser.parse_args()
    try:
        run(args.root)
    except Exception as exc:
        print(json.dumps({"timestamp_utc": utc_now(), "status": "failed",
                          "error_type": type(exc).__name__, "error": str(exc)}), flush=True)
        raise


if __name__ == "__main__":
    main()
