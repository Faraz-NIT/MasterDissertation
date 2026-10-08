#!/usr/bin/env python3
"""Fill Ollama's content-addressed cache from its official, TLS-verified registry.

The cloud proxy can follow HTTPS redirects while Ollama's redirect DNS precheck
cannot resolve the destination locally. Preserve TLS and SHA-256 verification.
Ollama pull then verifies these cached blobs and registers the official manifest.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path('/workspace/tools/ollama/models/blobs')
REGISTRY='https://registry.ollama.ai/v2/library/llama3.2/'


def verify(path, digest, size):
    if not path.exists() or path.stat().st_size != size:
        return False
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            h.update(block)
    return h.hexdigest() == digest.split(':',1)[1]


def fetch(entry):
    digest,size=entry['digest'],entry['size']
    target=ROOT/digest.replace(':','-')
    if verify(target,digest,size):
        print('Verified cached',digest,size,flush=True)
        return
    temporary=target.with_suffix('.partial')
    h=hashlib.sha256();count=0
    with urllib.request.urlopen(REGISTRY+'blobs/'+digest,timeout=120) as response,temporary.open('wb') as stream:
        for block in iter(lambda:response.read(8*1024*1024),b''):
            stream.write(block);h.update(block);count+=len(block)
    if count != size or h.hexdigest() != digest.split(':',1)[1]:
        raise RuntimeError('Size or SHA-256 mismatch for '+digest)
    temporary.replace(target)
    print('Downloaded and verified',digest,count,flush=True)


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(REGISTRY+'manifests/3b',timeout=30) as response:
        raw=response.read()
    manifest=json.loads(raw)
    Path('/workspace/tools/ollama/official_llama3.2_3b_manifest.json').write_bytes(raw)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch,[manifest['config'],*manifest['layers']]))


if __name__=='__main__':
    main()
