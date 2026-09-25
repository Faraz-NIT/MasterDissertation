# Contributing

Use a branch, a virtual environment and small synthetic fixtures. Run `python -m pytest -q` and `python -m compileall -q src scripts`. Optional-model tests skip only when the corresponding dependency is genuinely absent; the main code never substitutes a fake model under a literature baseline ID.

Each new constraint must modify the schema, grounding checks, optimizer and independent verifier together. Each new forecast must prove that its training window excludes future outcomes. Each new disturbance needs a deterministic keyed onset process, a true-versus-observed boundary test and a detection fixture. Keep the implementation matrix current.

Never change baseline definitions, test splits or hypothesis outcomes without recording it. Do not add private telemetry, retailer/customer identifiers, supplier contracts, keys or pretrained weights to the public repository.
