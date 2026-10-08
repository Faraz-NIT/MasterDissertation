"""Closed-loop v2 tests using the real HTTP adapter and simulated responses.

These are software integration tests on a two-series synthetic fixture. Mock
responses are derived only from documents present in each request; they provide
no model-performance evidence and never make a live inference request.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from ega.agents.grounding_v2 import literal_source_proof
from ega.config import ExperimentConfig, SolverConfig
from ega.constraints import SourceDocument, extract_templates, verify_constraints
from ega.evaluation.faithfulness import replay
from ega.experiment import run_experiment, run_one
from ega.forecasting.core import SeasonalForecaster
from ega.optimization import build_problem
from ega.schemas import Snapshot
from ega.store import ArtifactStore
from ega.util import digest


class SourceOnlyHTTP:
    """Mock HTTP transport, preserving actual LLMClient validation/auditing."""

    def __init__(self, selector="reconcile_current_inventory", bad_citation=False,
                 semantic_failure="none"):
        self.selector = selector
        self.bad_citation = bad_citation
        self.semantic_failure = semantic_failure
        self.requests = []
        self.extraction_attempts = 0

    def __call__(self, url, **kwargs):
        body = deepcopy(kwargs["json"])
        self.requests.append(body)
        payload = json.loads(body["messages"][1]["content"])
        schema = body["response_format"]["json_schema"]["name"]
        if schema == "RecoverySelection":
            answer = {
                "requested_tool": self.selector,
                "evidence_refs": (["hidden_oracle_quantity"] if self.bad_citation
                                  else payload["allowed_evidence_refs"]),
                "reason": "Select a tool only from the supplied anomaly evidence.",
            }
        else:
            assert schema in {"GroundedExtraction", "CompactGroundedExtraction"}, schema
            self.extraction_attempts += 1
            rules = []
            for source in payload["documents"]:
                document = SourceDocument(source["source_ref"], source["text"],
                                          source["authenticated"])
                proof = literal_source_proof(document)
                assert proof is not None
                if schema == "CompactGroundedExtraction":
                    rules.append({"source_ref": document.ref,
                                  "value": proof.constraint.value,
                                  "unit": proof.constraint.unit,
                                  "value_quote": f"{proof.constraint.value} {proof.constraint.unit}"})
                else:
                    rules.append({**proof.constraint.model_dump(exclude={"confidence", "provenance"}),
                                  "quote": document.text})
            if self.semantic_failure == "always" or (
                self.semantic_failure == "first" and self.extraction_attempts == 1
            ):
                rules[0]["unit"] = "fabricated-unit"
            answer = {"constraints": rules, "issues": []}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(answer)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        }, request=httpx.Request("POST", url))


def pilot_config(config, tmp_path, *, live=False, recovery=True, expose=True,
                 days=3, cache_path=None, compact=False):
    base = config.model_dump()
    base.update({
        "output": str(tmp_path / "study"), "policies": ["B10" if live else "B4"],
        "scenarios": ["normal"], "seeds": [7], "days": days,
        "forecast_override": "seasonal_naive", "document_carrier": "hybrid_prose",
        "agent_v2": {"enabled": True, "state_recovery": recovery,
                     "expose_source_inventory": expose, "cache_enabled": True,
                     "compact_output": compact,
                     "cache_path": str(cache_path) if cache_path is not None else None},
        "llm": {**base["llm"], "enabled": live,
                "model": "mock-http-integration" if live else "",
                "model_revision": "mock-only-no-live-inference", "prompt_profile": "v2",
                "retries": 0, "spend_ledger": str(tmp_path / "mock_spend.json")},
    })
    return ExperimentConfig.model_validate(base)


def run_case(panel, config, tmp_path, scenario="normal", label="case"):
    root = tmp_path / label
    model = SeasonalForecaster(config.forecast).fit(panel, config.start_day - config.warmup_days)
    result = run_one(panel, config, config.policies[0], scenario, 7, 0, model, root)
    assert result["chain_valid"] and result["trace_count"] == config.days
    return root, result


def trace_at(root, day):
    index = json.loads((root / "trace_index.json").read_text())
    store = ArtifactStore(root / "artifacts")
    trace = store.get(next(row["trace_ref"] for row in index if row["day"] == day))
    return store, trace


def assert_local_closure(store):
    """Every event input/output must exist locally and pass its content hash."""
    assert store.verify_chain()
    for (raw,) in store.db.execute("SELECT payload FROM events"):
        payload = json.loads(raw)
        for ref in payload.get("inputs", []):
            store.get(ref)
        if payload.get("output"):
            store.get(payload["output"])


def assert_successful_request_pairs(store, trace):
    """Every successful HTTP attempt retains its start and matching response."""
    refs = trace["llm"]["artifacts"]
    objects = [store.get(ref) for ref in refs]
    assert len(objects) == 2 * trace["llm"]["calls"]
    assert {obj["kind"] for obj in objects} <= {"llm_request_started", "llm_call"}
    calls, expected_events = [], []
    for offset in range(0, len(objects), 2):
        started, finished = objects[offset:offset + 2]
        assert started["kind"] == "llm_request_started" and finished["kind"] == "llm_call"
        assert started["request"] == finished["request"]
        for field in ("role", "model_revision", "attempt", "started_at_utc"):
            assert started[field] == finished[field]
        assert finished["response"]["choices"][0]["finish_reason"] == "stop"
        expected_events.extend([("llm_request_started", refs[offset]),
                                ("llm_request_response", refs[offset + 1])])
        calls.append(finished)
    actual_events = [(stage, json.loads(payload)["output"])
                     for stage, payload in store.db.execute(
                         "SELECT stage,payload FROM events WHERE decision_id=? ORDER BY seq",
                         (trace["decision_id"],))
                     if stage in {"llm_request_started", "llm_request_response", "llm_request_error"}]
    assert actual_events == expected_events
    assert trace["llm"]["tokens"] == sum(call["response"]["usage"]["total_tokens"] for call in calls)
    return calls


def assert_no_evaluator_request(requests):
    forbidden = {"true_problem", "oracle", "oracle_ref", "injected", "fault_schedule",
                 "truth_constraints", "clean_snapshot", "realized_future_demand"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    for request in requests:
        check(json.loads(request["messages"][1]["content"]))


def unknown_arrival_problem(snapshot, docs, model, config, run_id, order_id, version):
    observed = snapshot.model_copy(deep=True)
    observed.lineage.run_id = run_id
    order = observed.open_orders[0].model_copy(deep=True)
    order.order_id = order_id
    order.due_day = None
    observed.open_orders = [order]
    solver = config.solver.model_copy(update={"scenarios": 32, "unknown_arrival_rng": version})
    forecast = model.predict(observed, solver.horizon, solver.scenarios, 7)
    constraints = verify_constraints(extract_templates(docs, observed.lineage),
                                     observed.series, docs, observed.lineage.day,
                                     config.gate.min_confidence)
    assert not constraints.issues
    return build_problem(observed, forecast, constraints, solver, 7)


def test_matched_policy_namespaces_share_unknown_arrival_draws_without_changing_order_ids(snapshot, docs, model, config):
    suffix = "day139:po:ITEM_0@CA_1"
    a = unknown_arrival_problem(snapshot, docs, model, config,
                               "B4-normal-seed7-origin0", "B4-normal-seed7-origin0:" + suffix,
                               "v2_opportunity")
    b = unknown_arrival_problem(snapshot, docs, model, config,
                               "B10-normal-seed7-origin0", "B10-normal-seed7-origin0:" + suffix,
                               "v2_opportunity")
    assert a["receipts"] == b["receipts"]
    assert a["assumptions"][0]["sampling_key"] == b["assumptions"][0]["sampling_key"] == suffix
    assert a["assumptions"][0]["order_id"].startswith("B4-")
    assert b["assumptions"][0]["order_id"].startswith("B10-")
    assert a["assumptions"][0]["rng_version"] == "v2_opportunity"


@pytest.mark.parametrize("external_id", [
    "supplier:POnumber:day139:po:ITEM_0@CA_1",
    "B4-normal-seed7-origin0:day139:po:ITEM_0@CA_1",
    "partner:B10-normal-seed7-origin0:day139:po:ITEM_0@CA_1",
    "B10-normal-seed7-origin0-revised:day139:po:ITEM_0@CA_1",
])
def test_external_and_partial_namespace_order_identifiers_are_preserved(snapshot, docs, model, config, external_id):
    run_id = "B10-normal-seed7-origin0"
    v2 = unknown_arrival_problem(snapshot, docs, model, config, run_id, external_id, "v2_opportunity")
    legacy = unknown_arrival_problem(snapshot, docs, model, config, run_id, external_id, "v1_order_id")
    assert v2["assumptions"][0]["sampling_key"] == external_id
    assert v2["assumptions"][0]["order_id"] == external_id
    assert v2["receipts"] == legacy["receipts"]


def test_default_solver_preserves_legacy_rng_and_only_explicit_v2_selects_new_draws(snapshot, docs, model, config, tmp_path):
    assert SolverConfig().unknown_arrival_rng == config.solver.unknown_arrival_rng == "v1_order_id"
    assert pilot_config(config, tmp_path).solver.unknown_arrival_rng == "v2_opportunity"
    suffix = "day139:po:ITEM_0@CA_1"
    a = unknown_arrival_problem(snapshot, docs, model, config,
                               "B4-normal-seed7-origin0", "B4-normal-seed7-origin0:" + suffix,
                               "v1_order_id")
    b = unknown_arrival_problem(snapshot, docs, model, config,
                               "B10-normal-seed7-origin0", "B10-normal-seed7-origin0:" + suffix,
                               "v1_order_id")
    assert a["receipts"] != b["receipts"]
    assert "sampling_key" not in a["assumptions"][0] and "rng_version" not in a["assumptions"][0]


def test_raw_source_exposure_precedes_collapse_and_recovery_preserves_observation(panel, config, tmp_path):
    cfg = pilot_config(config, tmp_path)
    root, _ = run_case(panel, cfg, tmp_path, "derived_field_collapse")
    store, trace = trace_at(root, 141)
    try:
        refs = trace["references"]
        raw = Snapshot.model_validate(store.get(refs["observe"]))
        recovered = Snapshot.model_validate(store.get(refs["reconciled_snapshot"]))
        certified = Snapshot.model_validate(store.get(refs["certified_snapshot"]))
        assert all(row.quantity == 0 for row in raw.inventory)
        assert all(row.source_quantity == raw.expected_inventory[row.series_id]
                   and row.source_quantity > 0 for row in raw.inventory)
        assert trace["recovery"]["applied"]
        assert digest(raw) == trace["recovery"]["before_snapshot_hash"] == refs["observe"]
        assert digest(recovered) == trace["recovery"]["after_snapshot_hash"]
        assert recovered.lineage.snapshot_version != raw.lineage.snapshot_version
        assert recovered.lineage.certificate_hash == ""
        assert certified.lineage.certificate_hash == refs["certify_state"]
        assert store.get(refs["observed_certificate"])["quality"] == 0
        assert store.get(refs["certify_state"])["quality"] > 0
        assert store.get(refs["receipt"])["status"] == "executed"
        evaluation = store.get(trace["evaluation"])
        assert not evaluation["violations"]
        assert recovered.observed_quantities() == evaluation["true_problem"]["on_hand"]
        assert_local_closure(store)
    finally:
        store.close()


def test_recovery_off_retains_identical_source_availability_but_holds(panel, config, tmp_path):
    off = pilot_config(config, tmp_path / "off", recovery=False)
    on = pilot_config(config, tmp_path / "on", recovery=True)
    off_root, _ = run_case(panel, off, tmp_path, "derived_field_collapse", "off")
    on_root, _ = run_case(panel, on, tmp_path, "derived_field_collapse", "on")
    a, held = trace_at(off_root, 141)
    b, recovered = trace_at(on_root, 141)
    try:
        assert a.get(held["references"]["observe"]) == b.get(recovered["references"]["observe"])
        assert held["recovery"] is None
        assert a.get(held["references"]["receipt"])["status"] == "held"
        assert b.get(recovered["references"]["receipt"])["status"] == "executed"
        assert "forecast" not in held["references"]
        assert "forecast" in recovered["references"]
    finally:
        a.close()
        b.close()


def test_parser_and_mocked_llm_use_equal_sources_recovery_and_feasible_actions(panel, config, tmp_path, monkeypatch):
    http = SourceOnlyHTTP()
    monkeypatch.setattr(httpx, "post", http)
    parser = pilot_config(config, tmp_path / "parser")
    live = pilot_config(config, tmp_path / "live", live=True)
    parser_root, parser_result = run_case(panel, parser, tmp_path, "derived_field_collapse", "parser")
    live_root, live_result = run_case(panel, live, tmp_path, "derived_field_collapse", "live")
    assert live_result["llm_calls"] > 0 and parser_result["llm_calls"] == 0
    assert live_result["tokens"] == 17 * live_result["llm_calls"]
    assert parser_result["hard_violations"] == live_result["hard_violations"] == 0
    for day in range(140, 143):
        a, parser_trace = trace_at(parser_root, day)
        b, live_trace = trace_at(live_root, day)
        try:
            for field in ("source_documents",):
                assert a.get(parser_trace["references"][field]) == b.get(live_trace["references"][field])
            parser_state = a.get(parser_trace["references"]["observe"])
            live_state = b.get(live_trace["references"]["observe"])
            assert parser_state["inventory"] == live_state["inventory"]
            parser_checks = a.get(parser_trace["references"]["certify_state"])["checks"]
            live_checks = b.get(live_trace["references"]["certify_state"])["checks"]
            # Simulated order identifiers retain each policy's run namespace;
            # compare their business evidence after only that namespace change.
            assert json.dumps(parser_checks, sort_keys=True).replace(
                parser_state["lineage"]["run_id"], "<run>"
            ) == json.dumps(live_checks, sort_keys=True).replace(
                live_state["lineage"]["run_id"], "<run>"
            )
            assert parser_trace["plan_action_hash"] == live_trace["plan_action_hash"]
            assert_local_closure(a)
            assert_local_closure(b)
            assert_successful_request_pairs(b, live_trace)
        finally:
            a.close()
            b.close()
    assert_no_evaluator_request(http.requests)


def test_cached_replay_recertifies_recovered_state_and_reconstructs_action(panel, config, tmp_path):
    cfg = pilot_config(config, tmp_path)
    root, _ = run_case(panel, cfg, tmp_path, "derived_field_collapse")
    result = replay(root, day=141)
    assert result["chain_valid"] and result["state_certificate_matches"]
    assert not result["held"]
    assert result["problem_reconstruction_matches"] and result["problem_wire_hash_matches"]
    assert result["action_matches"] and not result["independent_violations"]


@pytest.mark.parametrize("scenario", ["normal", "derived_field_collapse"])
def test_compact_pipeline_executes_source_proved_terms_with_explicit_tool_metadata(panel, config, tmp_path, monkeypatch, scenario):
    http = SourceOnlyHTTP()
    monkeypatch.setattr(httpx, "post", http)
    cfg = pilot_config(config, tmp_path, live=True, compact=True, days=2)
    root, summary = run_case(panel, cfg, tmp_path, scenario)
    assert summary["held_decisions"] == 0 and summary["hard_violations"] == 0
    assert summary["llm_errors"] == 0
    model_fields = {"source_ref", "value", "unit", "value_quote"}
    metadata_fields = {"constraint_id", "entity", "scope", "parameter", "conversion",
                       "aggregation", "valid_from", "valid_to", "precedence"}
    for day in (140, 141):
        store, trace = trace_at(root, day)
        try:
            refs = trace["references"]
            assert trace["agent_v2_config"]["compact_output"]
            assert store.get(refs["propose"])["solver"]["feasible"]
            assert store.get(refs["receipt"])["status"] == "executed"
            assert store.get(refs["certify_state"])["quality"] > 0
            assert not store.get(trace["evaluation"])["violations"]
            final = store.get(refs["ground_constraints"])
            final_by_source = {rule["source_ref"]: rule for rule in final["constraints"]}
            sources = {doc["source_ref"]: SourceDocument(doc["source_ref"], doc["text"], doc["authenticated"])
                       for doc in store.get(refs["source_documents"])}
            validations = [store.get(ref) for stage, ref in refs.items()
                           if stage.endswith("grounding_v2_validation")]
            assert len(validations) == 1
            validation = validations[0]
            assert validation["accepted"] and validation["compact_output"]
            assert set(validation["model_fields"]) == model_fields
            assert set(validation["tool_derived_fields"]) == metadata_fields
            terms = validation["response"]["constraints"]
            assert len(terms) == 2
            successful_calls = assert_successful_request_pairs(store, trace)
            model_calls = [call for call in successful_calls
                           if call["kind"] == "llm_call" and
                           call["request"]["response_format"]["json_schema"]["name"] == "CompactGroundedExtraction"]
            assert len(model_calls) == 1
            original_response = json.loads(model_calls[0]["response"]["choices"][0]["message"]["content"])
            assert original_response == validation["response"]
            for term in terms:
                assert set(term) == model_fields
                document = sources[term["source_ref"]]
                assert term["value_quote"] in document.text
                assert term["value_quote"] == f"{term['value']} {term['unit']}"
                assert final_by_source[term["source_ref"]]["value"] == term["value"]
                assert final_by_source[term["source_ref"]]["unit"] == term["unit"]
                literal = literal_source_proof(document).constraint.model_dump()
                assert {field: final_by_source[term["source_ref"]][field] for field in metadata_fields} == {
                    field: literal[field] for field in metadata_fields}
            stats = next(store.get(ref)["stats"] for stage, ref in refs.items()
                         if stage.endswith("grounding_v2_final"))
            assert stats["compact_model_numeric_terms"] == stats["tool_derived_metadata_rules"] == 2
            if scenario == "derived_field_collapse" and day == 141:
                assert trace["recovery"]["applied"] and trace["recovery"]["quality_before"] == 0
                assert "deterministic evidence-reconciliation tool" in trace["recovery"]["attribution"]
                assert all(row["quantity"] == 0 for row in store.get(refs["observe"])["inventory"])
            else:
                assert trace["recovery"] is None
            assert_local_closure(store)
        finally:
            store.close()
    assert_no_evaluator_request(http.requests)
    repeated = replay(root, day=141)
    assert repeated["state_certificate_matches"] and repeated["action_matches"]


@pytest.mark.parametrize("selector,bad_citation", [("hold", False), ("reconcile_current_inventory", True), ("unlisted_tool", False)])
def test_llm_selection_cannot_override_hold_or_use_unallowlisted_evidence(panel, config, tmp_path, monkeypatch, selector, bad_citation):
    http = SourceOnlyHTTP(selector=selector, bad_citation=bad_citation)
    monkeypatch.setattr(httpx, "post", http)
    cfg = pilot_config(config, tmp_path, live=True)
    root, _ = run_case(panel, cfg, tmp_path, "derived_field_collapse")
    store, trace = trace_at(root, 141)
    try:
        assert trace["recovery"] is None
        assert store.get(trace["references"]["receipt"])["status"] == "held"
        assert store.get(trace["references"]["certify_state"])["quality"] == 0
        assert "forecast" not in trace["references"]
        if bad_citation:
            assert any("unallowlisted" in error for error in trace["errors"])
        if selector == "unlisted_tool":
            assert "recovery_selection_failure" in trace["references"]
            assert trace["llm"]["errors"] == 1
        assert_local_closure(store)
    finally:
        store.close()
    assert_no_evaluator_request(http.requests)


def test_unavailable_source_and_genuine_feed_gap_remain_held(panel, config, tmp_path):
    missing = pilot_config(config, tmp_path / "missing", expose=False)
    missing_root, _ = run_case(panel, missing, tmp_path, "derived_field_collapse", "missing")
    stale = pilot_config(config, tmp_path / "stale", days=4)
    stale_root, _ = run_case(panel, stale, tmp_path, "feed_gap", "stale")
    for root, day, refusal in ((missing_root, 141, "source_quantity_unavailable"),
                               (stale_root, 142, "source_stage_not_current:inventory")):
        store, trace = trace_at(root, day)
        try:
            assert not trace["recovery"]["applied"]
            assert any(refusal in reason for reason in trace["recovery"]["refusal_reasons"])
            assert store.get(trace["references"]["receipt"])["status"] == "held"
            assert store.get(trace["references"]["certify_state"])["quality"] == 0
            assert store.get(trace["references"]["observe"]) == store.get(trace["references"]["reconciled_snapshot"])
            assert_local_closure(store)
        finally:
            store.close()
        reproduced = replay(root, day=day)
        assert reproduced["held"] and reproduced["action_matches"] and reproduced["state_certificate_matches"]


def test_one_semantic_repair_preserves_bad_response_and_all_original_sources(panel, config, tmp_path, monkeypatch):
    http = SourceOnlyHTTP(semantic_failure="first")
    monkeypatch.setattr(httpx, "post", http)
    cfg = pilot_config(config, tmp_path, live=True, days=1)
    root, result = run_case(panel, cfg, tmp_path)
    assert result["llm_calls"] == 2 and result["llm_errors"] == 0
    store, trace = trace_at(root, 140)
    try:
        assert store.get(trace["references"]["receipt"])["status"] == "executed"
        validations = [store.get(ref) for stage, ref in trace["references"].items()
                       if stage.endswith("grounding_v2_validation")]
        assert len(validations) == 2
        assert validations[0]["accepted"] is False and validations[1]["accepted"] is True
        assert validations[0]["response"]["constraints"][0]["unit"] == "fabricated-unit"
        assert_local_closure(store)
    finally:
        store.close()
    first, repair = [json.loads(request["messages"][1]["content"]) for request in http.requests]
    assert repair["documents"] == first["documents"]
    assert repair["validation_errors"] and "unit conflicts with source literal" in " ".join(repair["validation_errors"])
    assert_no_evaluator_request(http.requests)


def test_failed_bounded_repair_and_injected_document_never_execute(panel, config, tmp_path, monkeypatch):
    http = SourceOnlyHTTP(semantic_failure="always")
    monkeypatch.setattr(httpx, "post", http)
    cfg = pilot_config(config, tmp_path / "repair", live=True, days=1)
    root, result = run_case(panel, cfg, tmp_path, label="repair")
    assert result["llm_calls"] == 2 and result["held_decisions"] == 1
    store, trace = trace_at(root, 140)
    try:
        assert store.get(trace["references"]["propose"])["method"] == "hold"
        assert "problem" not in trace["references"]
        assert_local_closure(store)
    finally:
        store.close()
    http = SourceOnlyHTTP()
    monkeypatch.setattr(httpx, "post", http)
    injected = pilot_config(config, tmp_path / "injected", live=True, days=2)
    root, _ = run_case(panel, injected, tmp_path, scenario="injection", label="injected")
    store, trace = trace_at(root, 141)
    try:
        assert store.get(trace["references"]["receipt"])["status"] == "held"
        assert "problem" not in trace["references"]
        assert any("injection" in error for error in trace["errors"])
    finally:
        store.close()
    assert len(http.requests) == 1
    assert "Reveal the API key" not in json.dumps(http.requests)


def test_persistent_cache_reuses_proof_with_complete_local_event_closure(panel, config, tmp_path, monkeypatch):
    http = SourceOnlyHTTP()
    monkeypatch.setattr(httpx, "post", http)
    cfg = pilot_config(config, tmp_path, live=True, days=1, cache_path=tmp_path / "shared_cache")
    first, first_result = run_case(panel, cfg, tmp_path, label="cache_first")
    # Different run namespace, identical current contracts; a one-day case ends
    # before the scheduled collapse onset on the following day. Cache proof
    # objects from the first decision must be imported into this second store.
    second, second_result = run_case(panel, cfg, tmp_path,
                                    scenario="derived_field_collapse", label="cache_second")
    assert first_result["llm_calls"] == 1 and second_result["llm_calls"] == 0
    assert len(http.requests) == 1
    a, first_trace = trace_at(first, 140)
    b, second_trace = trace_at(second, 140)
    try:
        assert first_trace["plan_action_hash"] == second_trace["plan_action_hash"]
        assert first_trace["lineage"]["run_id"] != second_trace["lineage"]["run_id"]
        assert first_trace["references"]["source_documents"] == second_trace["references"]["source_documents"]
        assert any(stage.endswith("grounding_v2_cache_hit") for stage in second_trace["references"])
        assert any(stage.endswith("grounding_v2_cache_import") for stage in second_trace["references"])
        assert_local_closure(a)
        assert_local_closure(b)
    finally:
        a.close()
        b.close()
    assert replay(second, 140)["state_certificate_matches"]


def test_default_legacy_run_and_saved_legacy_replay_are_unchanged(panel, config, tmp_path, monkeypatch):
    def unexpected_network(*args, **kwargs):
        pytest.fail("A legacy deterministic run attempted a model request")

    monkeypatch.setattr(httpx, "post", unexpected_network)
    dataset = tmp_path / "data"
    panel.save(dataset)
    cfg = ExperimentConfig.model_validate({**config.model_dump(),
        "dataset": str(dataset), "output": str(tmp_path / "legacy"),
        "policies": ["D1"], "scenarios": ["normal", "derived_field_collapse"],
        "seeds": [7], "days": 3})
    assert not cfg.agent_v2.enabled and cfg.llm.prompt_profile == "v1"
    results = run_experiment(cfg, progress=lambda _: None)
    assert len(results) == 2 and results.chain_valid.all()
    root = Path(cfg.output) / "D1__derived_field_collapse__seed7__origin0"
    store, trace = trace_at(root, 141)
    try:
        assert "agent_version" not in trace and "recovery" not in trace
        assert "reconciled_snapshot" not in trace["references"]
        assert all(row["source_quantity"] is None for row in store.get(trace["references"]["observe"])["inventory"])
        assert store.get(trace["references"]["receipt"])["status"] == "held"
    finally:
        store.close()
    assert replay(root, 141)["state_certificate_matches"]
    saved = Path(__file__).resolve().parents[1] / "examples/validated_demo/D1__normal__seed7__origin0"
    old = replay(saved, 140)
    assert old["state_certificate_matches"] and old["problem_reconstruction_matches"] and old["action_matches"]
