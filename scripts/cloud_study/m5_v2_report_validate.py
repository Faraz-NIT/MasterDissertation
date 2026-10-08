#!/usr/bin/env python3
"""Meaningful independent integrity failure tests for the pilot report reader."""
import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('v2report','/workspace/tools/m5_v2_report.py');report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)

class EvidenceIntegrityChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='m5-v2-reader-test-',dir='/tmp');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_valid_object_load(self):
        p=self.root/'artifacts/objects';p.mkdir(parents=True);value={'unit':'USD/unit','value':.55};ref=report.digest(value);(p/(ref+'.json')).write_text(report.canonical(value))
        reader=report.VerifiedReader(self.root,{});self.assertEqual(reader.load(ref),value);self.assertEqual(reader.verify_all(),1)
    def test_tampered_object_refused(self):
        p=self.root/'artifacts/objects';p.mkdir(parents=True);value={'unit':'USD/unit','value':.55};ref=report.digest(value);(p/(ref+'.json')).write_text(report.canonical({'unit':'USD','value':.55}))
        with self.assertRaisesRegex(ValueError,'Content hash differs'):report.VerifiedReader(self.root,{}).load(ref)
    def test_object_invalid_reference_refused(self):
        with self.assertRaisesRegex(ValueError,'Invalid content-addressed'):report.VerifiedReader(self.root,{}).load('../secret')
    def make_chain(self,tamper=False):
        p=self.root/'audit.sqlite';db=sqlite3.connect(p);db.executescript('CREATE TABLE events(seq INTEGER PRIMARY KEY,decision_id TEXT,stage TEXT,payload TEXT,previous_hash TEXT,event_hash TEXT); CREATE TABLE receipts(idempotency_key TEXT PRIMARY KEY,action_hash TEXT,payload TEXT);')
        payload={'output':'a'*64};event={'decision_id':'case:day1','stage':'source','payload':payload,'previous_hash':'0'*64};db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',(1,event['decision_id'],event['stage'],report.canonical({'output':'b'*64} if tamper else payload),'0'*64,report.digest(event)));db.commit();db.close();return p
    def test_valid_readonly_chain(self):
        p=self.make_chain();before=p.read_bytes();events,receipts,last=report.verify_chain(p);self.assertEqual(len(events),1);self.assertEqual(p.read_bytes(),before)
    def test_tampered_chain_refused(self):
        p=self.make_chain(tamper=True)
        with self.assertRaisesRegex(ValueError,'Audit event chain differs'):report.verify_chain(p)
    def test_pre_http_pair_and_order(self):
        common={'role':'supplier','started_at_utc':'2026-10-08T00:00:00Z','attempt':0,'request':{'messages':[]}}
        start={**common,'kind':'llm_request_started'};reply={**common,'kind':'llm_call'}
        artifacts=[('a'*64,start),('b'*64,reply)]
        events=[{'decision_id':'d','stage':'llm_request_started','seq':1,'payload':{'output':'a'*64}},{'decision_id':'d','stage':'llm_request_response','seq':2,'payload':{'output':'b'*64}}]
        result=report.audit_attempt_pairs(artifacts,events,'d',1,required=True);self.assertEqual(result['pre_http_starts'],1);self.assertEqual(result['paired_results'],1)
        events[0]['seq']=3
        with self.assertRaisesRegex(ValueError,'precedes persisted request'):report.audit_attempt_pairs(artifacts,events,'d',1,required=True)
    def test_unanswered_request_not_completed_evidence(self):
        start={'kind':'llm_request_started','role':'supplier','started_at_utc':'t','attempt':0,'request':{}}
        with self.assertRaisesRegex(ValueError,'unanswered persisted'):report.audit_attempt_pairs([('a'*64,start)],[],'d',1,required=True)
    def test_full_factorial_grid(self):
        config={'policies':['B4','B10'],'scenarios':['normal','feed_gap'],'seeds':[101,102],'origins':2};self.assertEqual(len(report.expected_grid(config)),16);self.assertIn(('B10','normal',102,1),report.expected_grid(config))
    def test_nested_evaluator_context_detected(self):
        payload={'documents':[],'context':[{'true_problem':{'hidden':1}}]};self.assertEqual(report.discover_keys(payload),['payload.context[0].true_problem'])
    def test_literal_source_is_data(self):
        payload={'documents':[{'text':'Do not use oracle_ref or true_problem.'}],'task':'Never use true_problem.'};self.assertEqual(report.discover_keys(payload),[])
    def test_unmatched_window_is_not_fair(self):
        a={'label':'parser','config':{'dataset':'m5','days':2}};b={'label':'llm','config':{'dataset':'m5','days':14}};result=report.fairness([a,b])[0];self.assertFalse(result['matched_registered_core_fields']);self.assertEqual(result['unmatched_core_fields'][0]['field'],'days')
    def test_repair_provenance_not_success_by_attempt(self):
        traces=[{'arm':'llm','grounding_stats':{'source_documents':2,'model_documents':0,'semantic_retries':1,'verified_documents':0},'grounding_complete':False}]
        events=[{'arm':'llm','mechanism':'grounding_v2_validation','artifact':{'accepted':False,'attempt':1}}];row=report.mechanism_aggregate(traces,events)[0];self.assertEqual(row['semantic_retries'],1);self.assertEqual(row['accepted_repair_batches'],0);self.assertEqual(row['grounding_complete_decisions'],0)
    def test_replay_summary_exposes_outcomes_not_hash_inventory(self):
        proof={'cases':[{'arm':'llm','scenario':'normal','day':1858,'source_file_hashes':{'opaque_object':'a'*64},'replay':{'state_certificate_matches':True,'action_matches':True,'held':False},'required_forecast_deletion':{'reconstruction_blocked':True},'original_source_bytes_unchanged':True,'deterministic_tool_counterfactuals':[{'factor':'budget','multiplier':.01,'action_changed':True,'violations':[]}]}]}
        items=report.posthoc_items({'posthoc_evidence':{'replay':proof}});serialized=json.dumps(items)
        self.assertNotIn('opaque_object',serialized);self.assertIn('Action match',serialized);self.assertIn('Action changed',serialized);self.assertIn('Forecast deletion blocked',serialized)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceIntegrityChecks);result=unittest.TextTestRunner(verbosity=2).run(suite)
    report.atomic_json('/workspace/tools/m5_v2_report_validation.json',{'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'reader_sha256':report.sha('/workspace/tools/m5_v2_report.py'),'validated':'Hash tampering, audit chain tampering, read-only preservation, path reference screening, exact grid identities, evaluator context leakage, mismatched horizons and repair attempt/success separation'})
    raise SystemExit(0 if result.wasSuccessful() else 1)
