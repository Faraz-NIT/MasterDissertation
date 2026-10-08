"""Tests of train-only gate selection and immutable follow-up boundaries."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ega.config import ExperimentConfig
from ega.schemas import Series


path = Path(__file__).resolve().parents[1] / "scripts/freshretailnet/gate_transfer.py"
spec = importlib.util.spec_from_file_location("fresh_gate_transfer", path)
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


def test_spending_cap_uses_all_seven_train_spends_and_registered_formula():
    result = transfer.choose_cap([1000, 1200, 1250, 1300, 1400, 1500, 1700])
    p95 = np.quantile([1000, 1200, 1250, 1300, 1400, 1500, 1700], .95)
    assert result["p95"] == pytest.approx(p95)
    assert result["selected_cap"] == min(2400, np.ceil(1.10 * p95 / 50) * 50)
    assert not result["evaluation_spends_used"]


def test_large_calibration_spends_cannot_exceed_eighty_percent_budget():
    assert transfer.choose_cap([3000] * 7)["selected_cap"] == 2400
    assert transfer.choose_cap([100] * 7, budget=100)["selected_cap"] == 80


@pytest.mark.parametrize("spends", [[1] * 6, [1] * 8, [1, 1, 1, 1, 1, 1, float('nan')], [1, 1, 1, 1, 1, 1, -1]])
def test_missing_or_invalid_proposed_spends_do_not_trigger_eval_fallback(spends):
    with pytest.raises(ValueError, match="exactly seven"):
        transfer.choose_cap(spends)


def test_final_config_changes_only_cap_version_and_delivery_paths(tmp_path):
    original = ExperimentConfig.model_validate({"policies": ["B4"], "agent_v2": {"enabled": True}})
    before = original.model_dump()
    cfg, changes = transfer.final_config(original, tmp_path / "arm", 1900, tmp_path / "cache", tmp_path / "spend")
    assert set(changes) <= {"output", "gate.max_spend", "gate.version", "agent_v2.cache_path", "llm.spend_ledger", "seeds"}
    assert cfg.gate.max_spend == 1900
    assert cfg.gate.two_person_spend == 2500
    assert cfg.gate.max_spend_deviation == original.gate.max_spend_deviation
    assert cfg.llm.model == original.llm.model
    assert cfg.llm.seed == original.llm.seed
    assert cfg.seeds == list(range(30))
    assert cfg.solver.model_dump() == original.solver.model_dump()
    assert original.model_dump() == before


def test_followup_llm_cannot_start_before_primary_completed_receipt(tmp_path):
    with pytest.raises(RuntimeError, match="waits for primary"):
        transfer.require_primary_complete(tmp_path)
    (tmp_path / "agents").mkdir()
    p = tmp_path / "agents/execution_complete.json"
    p.write_text(json.dumps({"status": "COMPLETE", "runs": 8}))
    with pytest.raises(RuntimeError, match="incomplete"):
        transfer.require_primary_complete(tmp_path)
    p.write_text(json.dumps({"status": "COMPLETE", "runs": 32}))
    assert transfer.require_primary_complete(tmp_path)["runs"] == 32


def test_calibration_panel_physically_excludes_later_training_and_eval(tmp_path):
    series = [Series(series_id=f"s{i}", item_id=f"i{i}", location=f"l{i}",
          supplier="supplier", department="d", family="f", cluster="c") for i in range(30)]
    rows = [{"series_id": item.series_id, "day_index": day,
             "dt": str(pd.Timestamp('2024-03-28') + pd.Timedelta(days=day))[:10],
             "sale_amount": .25 if day < 83 else 100_000,
             "stock_hour6_22_cnt": int(day % 2)} for item in series for day in range(97)]
    panel = transfer.training_panel(pd.DataFrame(rows), series, tmp_path / "flags.npy")
    assert panel.sales.shape == (30, 83)
    assert np.max(panel.sales) == 25
    assert panel.days == 83
    assert np.load(tmp_path / "flags.npy").shape == panel.sales.shape
    assert not panel.provenance["official_eval_values_loaded"]
    assert panel.provenance["latest_included_day"] == 82


def test_wrong_approval_threshold_is_not_silently_transferred(tmp_path):
    original = ExperimentConfig.model_validate({"policies": ["B4"], "agent_v2": {"enabled": True},
          "gate": {"two_person_spend": 3000}})
    with pytest.raises(ValueError, match="remain 2500"):
        transfer.final_config(original, tmp_path / "arm", 1900, tmp_path / "cache", tmp_path / "spend")


def test_followup_workload_is_registered_as_all_thirty_simulator_seeds():
    assert transfer.SEEDS == list(range(30))
    assert transfer.RUNS_PER_ARM == 120
    assert transfer.EXPECTED_RUNS == 480
    assert transfer.EXPECTED_DECISIONS == 3360
