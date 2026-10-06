from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

class SolverConfig(StrictConfig):
    horizon: int = Field(8, ge=2, le=90)
    scenarios: int = Field(8, ge=2, le=1000)
    time_limit: float = Field(20, gt=0)
    mip_gap: float = Field(0.001, ge=0, lt=1)
    risk_weight: float = Field(0.1, ge=0)
    cvar_alpha: float = Field(0.95, gt=0, lt=1)
    budget: float = Field(3000, gt=0)
    storage_per_location: float = Field(10000, gt=0)
    holding_rate: float = Field(0.015, gt=0)
    shortage_multiplier: float = Field(5, gt=0)
    transfer_cost: float = Field(0.3, ge=0)
    transfer_lead: int = Field(1, ge=1)
    allow_transfers: bool = True
    max_order_units: int = Field(1000, ge=1)

class GateConfig(StrictConfig):
    version: str = "gate-v2-spend-deviation-2026-10-06"
    min_quality: float = Field(0.7, ge=0, le=1)
    full_quality: float = Field(0.95, ge=0, le=1)
    min_confidence: float = Field(0.9, ge=0, le=1)
    max_spend: float = Field(1500, gt=0)
    two_person_spend: float = Field(2500, gt=0)
    # Gate v2: extra spend beyond the order-up-to baseline as a share of the budget (see docs/GATE_CALIBRATION.md).
    # Frozen 6 Oct 2026 at 0.03: between the 95th and 99th percentile of clean-day values in both calibration windows
    # (trips on about 3.5% of clean days). Other caps never tripped on clean days and were left as they were.
    max_spend_deviation: float = Field(0.03, ge=0)
    # Gate v1 cap, retired 6 Oct 2026. Accepted (never evaluated) so run manifests written before then still replay.
    max_deviation: float | None = None
    max_days_supply: float = Field(45, gt=0)
    max_dispersion: float = Field(4, gt=0)
    hold_budget: int = Field(2, ge=0)
    max_feed_age: int = Field(1, ge=0)
    fixed_level: Literal["advisory", "approval", "bounded", "full"] = "full"
    # Deterministic pattern screen that drops a document before any model reads it and vetoes a plan whose
    # sources failed it. Switch it off ONLY to measure the LLM's own resistance; label the run via `version`.
    injection_screen: bool = True

class ForecastConfig(StrictConfig):
    lookback: int = Field(56, ge=14)
    service_quantile: float = Field(0.95, gt=0.5, lt=1)
    deep_epochs: int = Field(5, ge=1)
    hidden_size: int = Field(32, ge=4)
    max_training_windows: int = Field(6000, ge=32)
    lgbm_estimators: int = Field(80, ge=1)
    chronos_model: str = "amazon/chronos-t5-tiny"
    chronos_revision: str | None = None
    censor_correction: bool = True

class LLMConfig(StrictConfig):
    enabled: bool = False
    provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = "medium"  # anthropic only; null for Haiku 4.5
    fallbacks: bool = True  # anthropic only: server-side refusal fallback; served model is recorded
    base_url: str = "http://localhost:11434/v1"
    model: str = ""
    model_revision: str = "unrecorded"
    api_key_env: str = "EGA_LLM_API_KEY"
    json_mode: Literal["schema", "json", "none"] = "schema"
    temperature: float = Field(0, ge=0, le=2)
    timeout: float = Field(60, gt=0)
    retries: int = Field(1, ge=0, le=5)
    rate_limit_retries: int = Field(30, ge=0)
    rate_limit_max_wait: float = Field(120, gt=0)
    max_calls: int = Field(500, ge=1)
    # Hard spend cap across every run that shares the ledger file (anthropic only). Prices are USD per 1M tokens.
    max_cost_usd: float | None = Field(None, gt=0)
    input_usd_per_mtok: float = Field(0, ge=0)
    output_usd_per_mtok: float = Field(0, ge=0)
    spend_ledger: str = "results/llm_spend.json"
    max_tokens: int = Field(2500, ge=128)
    seed: int = 42
    on_failure: Literal["hold", "deterministic"] = "hold"
    use_memory: bool = True

class QualityLayerConfig(StrictConfig):
    version: str = "synthetic-v1-NOT-telemetry-calibrated"
    calibrated: bool = False
    calibration_file: str | None = None
    rate_multiplier: float = Field(1, ge=0, le=10)
    onset_rate: float = Field(0.04, ge=0, le=1)
    min_duration: int = Field(1, ge=1)
    max_duration: int = Field(3, ge=1)
    magnitude: float = Field(2, gt=0)
    @model_validator(mode="after")
    def consistent(self):
        if self.max_duration < self.min_duration:
            raise ValueError("max_duration must be >= min_duration")
        if self.calibrated and not self.calibration_file:
            raise ValueError("A calibrated layer requires a pooled telemetry calibration file")
        return self

class ExperimentConfig(StrictConfig):
    dataset: str = "data/processed/demo"
    output: str = "results/demo"
    policies: list[str] = Field(default_factory=lambda: ["B1", "D0", "D1"])
    scenarios: list[str] = Field(default_factory=lambda: ["normal", "feed_gap", "duplicate_ingestion"])
    seeds: list[int] = Field(default_factory=lambda: [42])
    start_day: int = Field(140, ge=56)
    days: int = Field(14, ge=1)
    warmup_days: int = Field(14, ge=0)
    origin_stride: int = Field(28, ge=1)
    origins: int = Field(1, ge=1)
    forecast_override: str | None = None
    solver: SolverConfig = Field(default_factory=SolverConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    quality: QualityLayerConfig = Field(default_factory=QualityLayerConfig)
    harmful_abs_tolerance: float = Field(12, ge=0)
    harmful_rel_tolerance: float = Field(0.5, ge=0)
    escalation_cost: float = Field(2, ge=0)
    harmful_cost: float = Field(100, ge=0)
    trace_every: int = Field(1, ge=1)
    oracle: bool = True
    approval_mode: Literal["hold", "oracle"] = "hold"
    approval_delay: int = Field(1, ge=0)
    @model_validator(mode="after")
    def check(self):
        supported = {f"B{i}" for i in range(1,11)} | {"D0", "D1"}
        if not self.seeds or len(set(self.seeds))!=len(self.seeds):
            raise ValueError('Supply at least one unique independent replication seed')
        if not self.scenarios or len(set(self.scenarios))!=len(self.scenarios):
            raise ValueError('Supply distinct, nonempty scenario names')
        if len(set(self.policies))!=len(self.policies):raise ValueError('Duplicate policy IDs are not allowed')
        if self.trace_every!=1:raise ValueError('Complete daily traces are required; trace thinning is not implemented')
        if not self.policies or set(self.policies) - supported:
            raise ValueError(f"Policies must be drawn from {sorted(supported)}")
        if self.start_day - self.warmup_days < self.forecast.lookback:
            raise ValueError("Need a full forecasting history before warm-up")
        if any(p in {f"B{i}" for i in range(6,11)} for p in self.policies) and not self.llm.enabled:
            raise ValueError("B6-B10 require a real LLM. Use D1 for the explicitly non-LLM demonstration.")
        if self.llm.enabled and not self.llm.model:
            raise ValueError("Set llm.model to an installed/local or provider model identifier")
        return self

def load_config(path: str | Path) -> ExperimentConfig:
    with Path(path).open() as f:
        obj = yaml.safe_load(f)
    if not isinstance(obj, dict):
        raise ValueError("Configuration must be a YAML mapping")
    return ExperimentConfig.model_validate(obj)
