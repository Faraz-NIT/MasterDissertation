#!/usr/bin/env python3
"""Download the official small Qwen model with TLS and blob SHA/size checks."""
import concurrent.futures
import json
from pathlib import Path
import urllib.request
import download_ollama_verified as verified

verified.REGISTRY = 'https://registry.ollama.ai/v2/library/qwen2.5/'
verified.ROOT.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(verified.REGISTRY + 'manifests/0.5b', timeout=30) as response:
    raw = response.read()
manifest = json.loads(raw)
Path('/workspace/tools/ollama/official_qwen2.5_0.5b_manifest.json').write_bytes(raw)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(verified.fetch, [manifest['config'], *manifest['layers']]))
