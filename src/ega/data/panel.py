"""Canonical analytical panel, not exposed directly to agents."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from ..schemas import Series
from ..util import atomic_json, digest

@dataclass
class Panel:
    series: list[Series]
    sales: np.ndarray
    prices: np.ndarray
    calendar: pd.DataFrame
    provenance: dict
    def __post_init__(self):
        if self.sales.shape != self.prices.shape or self.sales.shape[0] != len(self.series):
            raise ValueError("Panel dimensions do not match")
        if self.sales.shape[1] != len(self.calendar):
            raise ValueError("Calendar does not align with panel")
        if not np.isfinite(self.sales).all() or (self.sales < 0).any():
            raise ValueError("Sales must be finite and nonnegative")
        ids = [s.series_id for s in self.series]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate item-location series")
    @property
    def n(self):
        return len(self.series)
    @property
    def days(self):
        return self.sales.shape[1]
    def eligibility(self, day: int) -> list[bool]:
        # Strictly past-only first-sale proxy; no future target is consulted.
        return (self.sales[:,:day] > 0).any(axis=1).tolist()
    def price_at(self, day: int) -> np.ndarray:
        # Use the most recent OBSERVED price, never the future week or a backward fill.
        if not 1 <= day <= self.days:
            raise ValueError("price_at requires at least one historical day")
        vals = self.prices[:,day-1].copy()
        return vals
    def save(self, path: str | Path):
        root=Path(path);root.mkdir(parents=True,exist_ok=True)
        pd.DataFrame([s.model_dump() for s in self.series]).to_csv(root/'series.csv',index=False)
        np.save(root/'sales.npy',self.sales.astype(np.float32),allow_pickle=False)
        np.save(root/'prices.npy',self.prices.astype(np.float32),allow_pickle=False)
        self.calendar.to_csv(root/'calendar.csv',index=False)
        atomic_json(root/'manifest.json', {**self.provenance,"series":self.n,"days":self.days,
                    "catalog_hash":digest(self.series),"date_index":"zero-based: index 0 = M5 d_1"})
    @classmethod
    def load(cls, path: str | Path):
        root=Path(path)
        required=['series.csv','sales.npy','prices.npy','calendar.csv','manifest.json']
        missing=[p for p in required if not (root/p).exists()]
        if missing:
            raise FileNotFoundError(f"Canonical dataset missing {missing}; use ega prepare or ega demo-data")
        return cls([Series.model_validate(x) for x in pd.read_csv(root/'series.csv').to_dict('records')],
                   np.load(root/'sales.npy',mmap_mode='r',allow_pickle=False),
                   np.load(root/'prices.npy',mmap_mode='r',allow_pickle=False),
                   pd.read_csv(root/'calendar.csv'),json.loads((root/'manifest.json').read_text()))
