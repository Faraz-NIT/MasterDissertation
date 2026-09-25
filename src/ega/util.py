"""Canonical serialization, content hashes, independent random streams and atomic files."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any
import numpy as np
from pydantic import BaseModel

def plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return plain(value.model_dump(mode="json"))
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value

def canonical(value: Any) -> str:
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def keyed_rng(seed: int, *keys: Any) -> np.random.Generator:
    # Never use Python's process-randomized hash() or a policy-dependent advancing stream.
    entropy = int(digest([seed, *keys])[:16], 16)
    return np.random.default_rng(entropy)

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf8") as f:
        f.write(canonical(value)); f.flush(); os.fsync(f.fileno()); tmp = f.name
    os.replace(tmp, path)

def environment() -> dict:
    packages = {}
    for name in ["numpy", "pandas", "scipy", "pydantic", "httpx", "PyYAML", "torch", "lightgbm", "chronos-forecasting"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}
