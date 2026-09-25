# Security and operational limits

This is a research simulator. It has **no real procurement/ERP execution endpoint**.

Supplier text and cells are untrusted data, including when they come from a configured trusted source. The source's `authenticated` flag represents application configuration, not a cryptographic signature. The numerical boundary validates schema, units, ranges, source references and known-template consistency. The model cannot edit physical inventory, grant itself tools, clear state failures or modify the optimizer's objective value.

The prompt-injection regular expressions are a heuristic screen, not proof of injection resistance. Obfuscated or novel attacks may pass. The absence of an executable shell/code/ERP tool is the main containment boundary in this implementation. Arbitrary URLs in supplier documents are not fetched. The workbook reader reads values, rejects formulas/macros/external links, and caps uncompressed ZIP size; it is not a full hostile-document sandbox.

Remote model requests can transmit every provided supplier/observation field to the configured provider. Use only synthetic/public experiment data without additional approval. API keys are read from an environment variable and not included in stored request headers. Raw prompts/responses are persisted for research reproducibility, so do not put private data or secrets inside prompts. Check provider retention and your institution's rules before enabling a remote model.

Local hashes and SQLite append-only conventions provide accidental-tamper detection. A user who controls the files can rewrite the whole chain. Genuine authenticated immutable storage requires signing, protected keys, immutable retention and trusted timestamps.

Idempotency prevents a duplicate decision from being applied twice in the running simulator. It does not provide a crash-atomic transaction spanning external actions and receipt persistence. Checkpoint/resume and a transactional outbox would be required for a real execution adapter. Reviewer labels are simulation metadata, not an authentication service. No production two-person approval claim is made.

Do not distribute researcher-only audit labels to participants. Do not commit `.env`, API keys, proprietary data, production logs or model access tokens. The supplied `.gitignore` is assistance, not a security boundary.
