from types import SimpleNamespace

from ega.agents.roles import SupplierConstraintAgent
from ega.config import ExperimentConfig
from ega.constraints import synthetic_contracts, render_prose, verify_constraints
from ega.data.synthetic import make_demo
from ega.schemas import ConstraintSet
from ega.simulator import InventoryEnvironment


def fixture():
    panel = make_demo(items=1, stores=2)
    cfg = ExperimentConfig()
    snapshot = InventoryEnvironment(panel, 140, 7, 'grounding-test', cfg).snapshot(56)
    rules = synthetic_contracts(panel.series, panel.price_at(140).tolist(),
                                panel.eligibility(140), 140, 7, 'normal', False, 3000)
    return cfg, snapshot, rules, render_prose(rules)


def test_invalid_rule_stops_requests_without_changing_hold_result():
    cfg, snapshot, rules, documents = fixture()
    bad = rules[0].model_copy(update={'unit': ''})

    class Client:
        config = SimpleNamespace(document_batch_size=1)
        calls = 0

        def ask(self, *args):
            self.calls += 1
            assert self.calls == 1, 'Later documents cannot repair this invalid active rule'
            return SimpleNamespace(constraints=[bad], issues=[])

    client = Client()
    result = SupplierConstraintAgent().run(snapshot, documents, cfg.gate, client)
    full = verify_constraints(ConstraintSet(lineage=snapshot.lineage,
        constraints=[bad, *rules[1:]]), snapshot.series, documents, 140)
    assert client.calls == 1
    assert any('dimensional mismatch' in issue for issue in result.issues)
    assert any('dimensional mismatch' in issue for issue in full.issues)


def test_incomplete_but_valid_batches_continue_to_full_coverage():
    cfg, snapshot, rules, documents = fixture()
    by_source = {c.source_ref: c for c in rules}

    class Client:
        config = SimpleNamespace(document_batch_size=1)
        calls = 0

        def ask(self, role, payload, *args):
            self.calls += 1
            return SimpleNamespace(constraints=[by_source[payload['documents'][0]['source_ref']]],
                                   issues=[])

    client = Client()
    result = SupplierConstraintAgent().run(snapshot, documents, cfg.gate, client)
    assert client.calls == len(documents)
    assert not result.issues
    assert len(result.constraints) == len(rules)
