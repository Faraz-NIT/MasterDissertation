"""Build new train-selected panels and fit one LightGBM family from raw files."""
from __future__ import annotations
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from lightgbm import LGBMRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import OUT, ROOT, dump, sha


def select(stats, label, lower, upper):
    eligible = stats[(stats["mean"] >= lower) & (stats["mean"] <= upper)].copy()
    eligible["hash"] = eligible["series_id"].map(lambda s: __import__("hashlib").sha256((label+s).encode()).hexdigest())
    eligible = eligible.sort_values(["mean", "hash"]).reset_index(drop=True)
    eligible["stratum"] = np.minimum(2, np.arange(len(eligible))*3//len(eligible))
    chosen = pd.concat([g.sort_values("hash").head(10) for _, g in eligible.groupby("stratum")])
    chosen = chosen.sort_values("series_id").reset_index(drop=True)
    assert len(chosen) == 30 and chosen.series_id.nunique() == 30
    return chosen, len(eligible)


def prepare_m5():
    raw = ROOT / "data/raw/m5"
    sales = raw / "sales_train_evaluation.csv"
    header = pd.read_csv(sales, nrows=0).columns
    dcols = sorted([c for c in header if c.startswith("d_")], key=lambda s: int(s[2:]))
    origin = len(dcols)-7
    selection_days = dcols[origin-112:origin-56]
    meta = pd.read_csv(sales, usecols=["item_id", "dept_id", "cat_id", "store_id", "state_id", *selection_days])
    meta = meta[meta.cat_id.eq("FOODS")].copy()
    meta["series_id"] = meta.item_id + "@" + meta.store_id
    meta["mean"] = meta[selection_days].mean(axis=1)
    chosen, eligible = select(meta, "fresh-ollama-M5-v1:", .5, 30)
    ids = set(chosen.series_id)
    parts = []
    for chunk in pd.read_csv(sales, chunksize=512):
        sid = chunk.item_id + "@" + chunk.store_id
        selected = chunk.loc[sid.isin(ids)].copy()
        if not selected.empty:
            selected["series_id"] = sid.loc[selected.index]
            parts.append(selected)
    rows = pd.concat(parts).set_index("series_id").loc[chosen.series_id]
    daily = rows[dcols].to_numpy(dtype=float)
    calendar = pd.read_csv(raw / "calendar.csv").set_index("d").loc[dcols]
    dates = calendar.date.tolist()
    data = {"dataset": "M5", "series_ids": chosen.series_id.tolist(), "sales": daily,
            "dates": dates, "origin": origin,
            "metadata": chosen[["series_id", "item_id", "dept_id", "store_id", "state_id", "mean", "stratum"]].to_dict("records")}
    receipt = {"dataset": "M5", "series": 30, "products": int(chosen.item_id.nunique()),
               "stores": int(chosen.store_id.nunique()), "history_days": origin, "evaluation_days": 7,
               "selection": "Training-only volume strata, ten hash-ranked FOODS pairs per stratum",
               "eligible_series": eligible, "selection_last_day_exclusive": origin-56,
               "quantity": "Published unit sales", "raw_files": {p.name: sha(p) for p in [sales, raw/"calendar.csv"]}}
    return data, receipt


def prepare_retailnet():
    raw = ROOT / "data/raw/freshretailnet"
    key = ["store_id", "product_id"]
    train_parts = []
    for batch in pq.ParquetFile(raw/"train.parquet").iter_batches(batch_size=100000, columns=key+["dt", "sale_amount"]):
        train_parts.append(batch.to_pandas())
    train = pd.concat(train_parts, ignore_index=True)
    assert len(train) == 4500000 and not train.duplicated(key+["dt"]).any()
    dates = sorted(train.dt.unique())
    assert len(dates) == 90
    early = train[train.dt.isin(dates[:62])]
    stats = early.groupby(key).sale_amount.agg(["mean", "count"]).reset_index()
    stats = stats[stats["count"].eq(62)].copy()
    stats["series_id"] = [f"FRN_{int(p)}@S{int(s)}" for s,p in zip(stats.store_id,stats.product_id)]
    chosen, eligible = select(stats, "fresh-ollama-RetailNet-v1:", .02, 1)
    pairs = set(map(tuple, chosen[key].to_numpy()))
    eval_parts = []
    evaluation_dates = set()
    full_rows = 0
    for batch in pq.ParquetFile(raw/"eval.parquet").iter_batches(batch_size=100000, columns=key+["dt", "sale_amount"]):
        part = batch.to_pandas(); full_rows += len(part); evaluation_dates.update(part.dt.unique())
        mask = [(s,p) in pairs for s,p in zip(part.store_id,part.product_id)]
        eval_parts.append(part.loc[mask])
    assert full_rows == 350000 and len(evaluation_dates) == 7
    evaluation_dates = sorted(evaluation_dates)
    assert min(evaluation_dates) > max(dates)
    index = pd.MultiIndex.from_frame(train[key])
    selected = train.loc[index.isin(pd.MultiIndex.from_tuples(list(pairs)))].copy()
    both = pd.concat([selected,*eval_parts])
    both["series_id"] = [f"FRN_{int(p)}@S{int(s)}" for s,p in zip(both.store_id,both.product_id)]
    assert len(both) == 30*97 and not both.duplicated(["series_id","dt"]).any()
    all_dates = dates + evaluation_dates
    daily = both.pivot(index="series_id", columns="dt", values="sale_amount").loc[chosen.series_id,all_dates].to_numpy()*100
    data = {"dataset": "RetailNet", "series_ids": chosen.series_id.tolist(), "sales": daily,
            "dates": all_dates, "origin": 90, "metadata": chosen.to_dict("records")}
    receipt = {"dataset": "Dingdong-Inc/FreshRetailNet-50K", "label": "RetailNet", "series": 30,
               "products": int(chosen.product_id.nunique()), "stores": int(chosen.store_id.nunique()),
               "training_days": 90, "evaluation_days": 7, "source_train_rows_checked": len(train),
               "source_eval_rows_checked": full_rows, "selection_last_day_exclusive": 62,
               "selection": "Training-only volume strata, ten hash-ranked pairs per stratum",
               "eligible_series": eligible, "quantity": "Published normalized sales multiplied by 100; not physical units",
               "raw_files": {p.name: sha(p) for p in [raw/"train.parquet",raw/"eval.parquet"]},
               "release_revision": "08c1fab7f9257bc73679d415d65d644165d351d4", "license": "CC-BY-4.0"}
    return data, receipt


def features(history, index, date):
    last = np.asarray(history[-28:])
    return [history[-k] for k in (1,7,14,28)] + [last[-7:].mean(), last.mean(), last.std(),
        float((last>0).mean()), index, pd.Timestamp(date).dayofweek, pd.Timestamp(date).month]


def train(data):
    sales = data["sales"]; origin = data["origin"]; dates = data["dates"]
    x, y = [], []
    start = max(28, origin-365)
    for i in range(30):
        for t in range(start,origin):
            x.append(features(sales[i,:t],i,dates[t])); y.append(sales[i,t])
    model = LGBMRegressor(objective="regression", n_estimators=150, max_depth=5,
        num_leaves=20, min_child_samples=15, n_jobs=1, verbosity=-1,
        random_state=20261009, deterministic=True, force_col_wise=True)
    model.fit(np.asarray(x), np.asarray(y))
    paths = sales[:,:origin].copy(); forecast = np.empty((30,14))
    future_dates = pd.date_range(pd.Timestamp(dates[origin]), periods=14).strftime("%Y-%m-%d").tolist()
    for step in range(14):
        frame = pd.DataFrame(np.asarray([features(paths[i],i,future_dates[step]) for i in range(30)]),columns=model.feature_name_)
        prediction = np.maximum(0,model.predict(frame))
        forecast[:,step] = prediction
        paths = np.c_[paths,prediction]
    # Safety-stock scale uses historical weekly changes, not evaluation residuals.
    history = sales[:,max(0,origin-56):origin]
    sd = np.std(history[:,7:]-history[:,:-7],axis=1)/np.sqrt(2)
    data.update(forecast=forecast, residual_sd=sd, historical_mean=history.mean(axis=1),
                groups=np.arange(30)%3)
    folder = OUT/"data"/data["dataset"]/f"origin_{origin}"
    folder.mkdir(parents=True,exist_ok=False)
    np.savez_compressed(folder/"panel_and_forecast.npz", sales=sales, forecast=forecast,
        residual_sd=sd, historical_mean=data["historical_mean"],groups=data["groups"])
    dump(folder/"catalog.json", {k:data[k] for k in ("dataset","series_ids","dates","origin","metadata")})
    model.booster_.save_model(str(folder/"lightgbm.txt"))
    dump(folder/"training.json", {"model_family":"LightGBM", "models_fitted":1,
        "training_end_exclusive":origin,"training_rows":len(y),"forecast_mode":"14-day recursive, no evaluation sales as inputs",
        "historical_sales_correction":False,"retail_llm_fine_tuning":False,
        "forecast_sha256":sha(folder/"panel_and_forecast.npz"),"model_sha256":sha(folder/"lightgbm.txt")})
    return data


if __name__ == "__main__":
    (OUT/"data").mkdir(parents=True,exist_ok=True)
    receipts = []
    for builder in (prepare_m5,prepare_retailnet):
        data,receipt = builder()
        receipt["rolling_origins"] = [data["origin"]-7,data["origin"]]
        for origin in receipt["rolling_origins"]:
            train(dict(data,origin=origin))
        receipts.append(receipt)
        print(json.dumps({"dataset":data["dataset"],"series":30,"origins":receipt["rolling_origins"],"forecast":"freshly fitted LightGBM per origin; one model family"}),flush=True)
    dump(OUT/"data/preparation_receipt.json", {"status":"VERIFIED","prepared_at_utc":datetime.now(timezone.utc).isoformat(),
        "no_previous_results_or_forecasts_loaded":True,"panels":receipts})
