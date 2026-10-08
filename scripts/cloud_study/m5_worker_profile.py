#!/usr/bin/env python3
"""Disclosed source-format conventions for a frozen simulator worker profile.

Only FORMAT_CONVENTIONS and public environment provenance are extended. Source
documents, quantities, labels, extraction schemas, validators, gates, solvers,
model selection and experiment settings are not changed. Every actual LLM call
records the resulting conventions in its request payload.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys

PROMPT_EXTENSION = (
    'Copy each source rule\'s entity identifier exactly, including its complete '
    'item-location suffix such as @store when present; do not replace a stated '
    'series identifier with an item-only identifier. Preserve the source_ref '
    'of the document containing that rule. Copy parameter, numeric value, unit, '
    'scope, aggregation, validity and precedence exactly as stated. Preserve '
    'compound units such as USD/unit rather than shortening them to USD. '
    'The published deterministic RULE carrier has this positional field order: '
    'RULE constraint_id | entity | scope | parameter | value | unit | conversion '
    '| aggregation | valid_from | valid_to | precedence. The final field is '
    'precedence; copy it, do not invent a default. This grammar applies only '
    'when a source explicitly contains a RULE line. In prose, read the same '
    'fields from the clause itself. These are format conventions, not expected '
    'answers. Return every supplied active rule once, preserving its own '
    'document reference; report any unresolved ambiguity explicitly.'
)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def activate(profile):
    """Apply only the two disclosed runtime extensions before CLI imports."""
    actual_wrapper = str(Path(__file__).resolve())
    if profile.get('wrapper') != actual_wrapper or profile.get('wrapper_sha256') != sha256(__file__):
        raise ValueError('Frozen worker wrapper path or SHA-256 differs from actual script')
    sidecar = Path(profile['sidecar'])
    if sha256(sidecar) != profile['sidecar_sha256']:
        raise ValueError('Frozen worker profile sidecar changed before execution')
    extension_sha = hashlib.sha256(PROMPT_EXTENSION.encode()).hexdigest()
    if profile.get('prompt_extension_sha256') not in (None, extension_sha):
        raise ValueError('Frozen prompt-extension digest differs from actual conventions')
    from ega import util
    original_environment = util.environment
    def profiled_environment():
        return {**original_environment(), 'execution_profile': profile}
    util.environment = profiled_environment
    from ega.agents import roles
    roles.FORMAT_CONVENTIONS = roles.FORMAT_CONVENTIONS + ' ' + PROMPT_EXTENSION
    return profile


def main(argv=None):
    raw = os.environ.get('M5_EXECUTION_PROFILE_JSON')
    if not raw:
        print('Worker profile must be supplied by its hash-validating execution driver', file=sys.stderr)
        return 2
    try:
        profile = json.loads(raw)
        activate(profile)
        from ega.cli import main as cli_main
        return cli_main(argv)
    except (ValueError, OSError, KeyError) as exc:
        print('Worker profile refused: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
