"""Field-level grounding benchmark with labels kept out of extraction requests."""
from __future__ import annotations
import json
from pathlib import Path
from ..constraints import SourceDocument,extract_templates,verify_constraints,render_templates,synthetic_contracts
from ..schemas import Lineage,Series,ConstraintSet
from ..data.synthetic import make_demo
from ..agents.llm import LLMClient,Extraction,ModelUnavailable
from ..store import ArtifactStore
from ..util import atomic_json,canonical

FIELDS=['entity','scope','parameter','value','unit','conversion','aggregation','valid_from','valid_to','precedence','source_ref']

def signature(c):return canonical({k:c[k] for k in FIELDS})

def make_corpus(output,prose_only=False):
    panel=make_demo(items=1,stores=2,days=180);cases=[]
    for i,scenario in enumerate(['normal','aggregate_moq','foreign_unit_moq','pack_change','capacity_cut','eligibility_change']):
        rules=synthetic_contracts(panel.series,panel.price_at(140).tolist(),panel.eligibility(140),140,7,scenario,True,3000)
        sources=render_templates(rules,variant=i%2)
        documents=[{'ref':d.ref,'text':d.text,'authenticated':d.authenticated} for d in sources]
        if prose_only:
            # Preserve all semantic fields, but remove the deterministic RULE carrier.
            for d,r in zip(documents,rules):
                d['text']=(f'Rule {r.constraint_id}. For entity {r.entity}, scope {r.scope}, '
                    f'{r.parameter} is {r.value} {r.unit}. Aggregation level: {r.aggregation}. '
                    f'Effective from day {r.valid_from} to day {r.valid_to}, both inclusive. '
                    f'Precedence {r.precedence}. Conversion: {r.conversion}.')
        cases.append({'case_id':scenario,'day':140,'series':[s.model_dump() for s in panel.series],
                      'documents':documents,'expected':[r.model_dump() for r in rules],
                      'carrier':'controlled_prose' if prose_only else 'deterministic_template'})
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(c)+'\n' for c in cases),encoding='utf8')
    return len(cases)

def evaluate_corpus(corpus,output,llm_config=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);store=ArtifactStore(output/'artifacts')
    client=LLMClient(llm_config,store) if llm_config is not None else None
    results=[]
    try:
        for line in Path(corpus).read_text().splitlines():
            if not line.strip():continue
            case=json.loads(line);series=[Series.model_validate(s) for s in case['series']]
            docs=[SourceDocument(**d) for d in case['documents']]
            lineage=Lineage(snapshot_version='grounding-benchmark',run_id=case['case_id'],day=case['day'])
            if client:
                values=[];issues=[]
                for start in range(0,len(docs),6):
                    try:
                        response=client.ask('constraint extraction benchmark',{'documents':[d.payload() for d in docs[start:start+6]],
                            'day':case['day'],'known_entities':[s.model_dump() for s in series]},Extraction)
                        values.extend(response.constraints);issues.extend(response.issues)
                    except ModelUnavailable as exc:issues.append(str(exc))
                raw=ConstraintSet(lineage=lineage,constraints=values,issues=issues)
            else:raw=extract_templates(docs,lineage)
            verified=verify_constraints(raw,series,docs,case['day'])
            expected={signature(c) for c in case['expected']};actual={signature(c.model_dump()) for c in raw.constraints}
            tp=len(expected&actual);false=len(actual-expected);missing=len(expected-actual)
            results.append({'case_id':case['case_id'],'carrier':case.get('carrier','user_supplied'),
                'whole_set_exact_match':actual==expected,'field_tuple_precision':tp/len(actual) if actual else None,
                'field_tuple_recall':tp/len(expected) if expected else 1,'false_constraints':false,'omitted_constraints':missing,
                'escalated':bool(verified.issues),'residual_errors_eligible_for_solver':false if not verified.issues else 0,
                'issues':verified.issues,'extraction_ref':store.put(raw),'verification_ref':store.put(verified)})
        atomic_json(output/'grounding_results.json',{'mode':'real_llm' if client else 'deterministic_template',
            'warning':'Controlled carrier benchmark, not a validated natural-language dataset. No expected labels are sent to the model.',
            'cases':results,'llm_calls':client.calls if client else 0,'tokens':client.tokens if client else 0})
        return results
    finally:store.close()
