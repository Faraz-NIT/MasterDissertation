#!/usr/bin/env python3
import importlib.util,unittest
spec=importlib.util.spec_from_file_location('v2assess','/workspace/tools/m5_v2_assess.py');assess=importlib.util.module_from_spec(spec);spec.loader.exec_module(assess)
report=assess.report
class IndependentSourceChecks(unittest.TestCase):
    def document(self,text):return {'source_ref':'contract/supplier:capacity:10','text':text,'authenticated':True,'sha256':report.digest(text)}
    def test_six_grammars(self):
        texts=[
          'Contract clause supplier:capacity:10 (precedence 10, aggregation supplier_order): supplier must comply with capacity = 400.0 unit at supplier scope, valid from day 10 to day 10 inclusive; conversion none.',
          'Rule supplier:capacity:10. For entity supplier, scope supplier, capacity is 400.0 unit. Aggregation level: supplier_order. Effective from day 10 to day 10, both inclusive. Precedence 10. Conversion: none.',
          'Agreement supplier:capacity:10: supplier has a capacity term of 400.0 unit. Coverage: supplier; accounting group: supplier_order; effective days 10 to 10 inclusive. Priority is 10; conversion factor is none.',
          'The portfolio agreement portfolio:budget:10 sets budget at 3000.0 USD for portfolio. Its accounting group is portfolio. Priority 10 applies throughout days 10 to 10 inclusive, with conversion none.',
          "Between day 10 and day 10 inclusive, supplier's supplier agreement supplier:capacity:10 allows capacity of 400.0 unit. Book the term at supplier_order; apply precedence 10 and conversion none.",
          'For portfolio, portfolio agreement portfolio:budget:10 specifies 3000.0 USD for budget. The rule lasts from day 10 through day 10 inclusive. Its priority is 10, accounting group portfolio, and conversion factor none.'
        ]
        for text in texts:
            rule,grammar,span=assess.inverse(self.document(text));self.assertEqual(rule['valid_from'],10);self.assertEqual(rule['precedence'],10);self.assertIsNone(rule['conversion']);self.assertIn(span,text)
    def test_source_digest_change_rejected(self):
        doc=self.document('unsupported');doc['text']='changed'
        with self.assertRaisesRegex(ValueError,'digest mismatch'):assess.inverse(doc)
    def test_unrecognised_language_rejected(self):
        with self.assertRaisesRegex(ValueError,'unique independent'):assess.inverse(self.document('Capacity 400.0 unit, probably.'))
    def test_validity_and_precedence(self):
        low={'entity':'supplier','parameter':'capacity','value':1000.,'unit':'unit','conversion':None,'valid_from':1,'valid_to':10,'precedence':1};high={**low,'value':400.,'precedence':2};expired={**low,'value':0.,'valid_to':2,'precedence':99}
        active,conflicts=assess.active_rules([low,high,expired],5);self.assertEqual(active,[high]);self.assertEqual(conflicts,[])
    def test_equal_precedence_conflict_preserved(self):
        a={'entity':'s','parameter':'capacity','value':1000.,'unit':'unit','conversion':None,'valid_from':1,'valid_to':10,'precedence':1};b={**a,'value':400.};active,conflicts=assess.active_rules([a,b],5);self.assertEqual(len(conflicts),1)
    def call(self,unit='unit',quote='400.0 unit'):
        text='Agreement supplier:capacity:10: supplier has a capacity term of 400.0 unit. Coverage: supplier; accounting group: supplier_order; effective days 10 to 10 inclusive. Priority is 10; conversion factor is none.';doc=self.document(text)
        obj={'request':{'messages':[{'role':'user','content':report.canonical({'documents':[doc]})}]},'response':{'choices':[{'message':{'content':report.canonical({'constraints':[{'source_ref':doc['source_ref'],'value':400.,'unit':unit,'value_quote':quote}],'issues':[]})},'finish_reason':'stop'}]}}
        return obj,{doc['source_ref']:doc}
    def test_model_terms_do_not_credit_metadata(self):
        call,docs=self.call();result=assess.score_numeric_call(call,docs,'initial');self.assertTrue(result['complete_exact_numeric_batch']);self.assertNotIn('entity',result['compact_model_fields']);self.assertIn('entity',result['tool_metadata_fields'])
    def test_unit_and_quote_errors_are_retained(self):
        call,docs=self.call(unit='USD',quote='400 unit');result=assess.score_numeric_call(call,docs,'repair');self.assertFalse(result['complete_exact_numeric_batch']);self.assertEqual(result['checks'][0]['errors'],['unit','value_quote']);self.assertEqual(result['false_numeric_terms'],1)
    def test_duplicate_term_not_exact(self):
        call,docs=self.call();obj=__import__('json').loads(call['response']['choices'][0]['message']['content']);obj['constraints']*=2;call['response']['choices'][0]['message']['content']=report.canonical(obj);result=assess.score_numeric_call(call,docs,'initial');self.assertFalse(result['complete_exact_numeric_batch']);self.assertEqual(result['exact_numeric_terms'],0)
    def selector_call(self,current=True,both=True,requested='reconcile_current_inventory'):
        refs=['stock_movement_balance']+(['inventory_distribution_shift'] if both else [])
        payload={'allowed_tools':['reconcile_current_inventory','hold'],'anomalies':[{'name':ref,'outcome':'hard_fail'} for ref in refs],'decision_day':10,'source_inventory_complete':True,'stage_days':{'inventory':10 if current else 9,'sales':10,'products':10}}
        answer={'requested_tool':requested,'evidence_refs':refs}
        return {'request':{'messages':[{'role':'user','content':report.canonical(payload)}]},'response':{'choices':[{'message':{'content':report.canonical(answer)},'finish_reason':'stop'}]}}
    def test_current_supported_recovery_selection(self):
        score=assess.score_recovery_selection(self.selector_call());self.assertTrue(score['instruction_compliant']);self.assertEqual(score['expected_tool'],'reconcile_current_inventory')
    def test_stale_feed_recovery_request_is_semantic_error(self):
        score=assess.score_recovery_selection(self.selector_call(current=False,both=False));self.assertFalse(score['instruction_compliant']);self.assertEqual(score['expected_tool'],'hold');self.assertIn('requested_tool_does_not_follow_observable_conditions',score['semantic_errors'])
    def test_missing_second_anomaly_is_not_eligible(self):
        score=assess.score_recovery_selection(self.selector_call(both=False));self.assertFalse(score['instruction_compliant']);self.assertFalse(score['both_required_anomalies_present'])
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IndependentSourceChecks));report.atomic_json('/workspace/tools/m5_v2_assess_validation.json',{'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'assessor_sha256':report.sha('/workspace/tools/m5_v2_assess.py'),'scope':'Independent public/hybrid inverses, source authentication/hash refusal, validity/precedence, metadata attribution, numeric unit/quote/duplicate failure detection and selector current-source/anomaly instruction compliance'});raise SystemExit(0 if result.wasSuccessful() else 1)
