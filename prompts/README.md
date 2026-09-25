# Prompt provenance

The authoritative system instructions and response schemas are in `src/ega/agents/llm.py`. Each role supplies its task and allowed evidence/tool references in `src/ega/agents/roles.py`. Runtime calls record the exact request, raw response, supplied model revision, token counts and content hashes in the artifact store. This directory deliberately does not maintain a second, potentially inconsistent prompt copy.

Prompts request typed evidence and concise observations, not a hidden chain-of-thought transcript. Supplier text and earlier free-form peer messages are untrusted observations. Changes to role instructions must be versioned and evaluated as prompt changes, not silently merged into a baseline comparison.
