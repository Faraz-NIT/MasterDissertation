"""Authenticated sources, typed grounding, deterministic normalization and conflict checks."""
from __future__ import annotations
import re
from dataclasses import dataclass
import numpy as np
from .schemas import Constraint, ConstraintSet, Lineage, Series
from .util import digest, keyed_rng

INJECTION_PATTERNS=[r'ignore\s+(all\s+)?(previous|prior|system|policy|instructions)',
                    r'(reveal|print|send|exfiltrate).{0,50}(secret|api.?key|password|system prompt)',
                    r'(execute|run).{0,25}(shell|bash|curl|python)',r'<\|.*(system|assistant).*\|>']

def screen_injection(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p,text,re.I|re.S)]

@dataclass(frozen=True)
class SourceDocument:
    ref: str
    text: str
    authenticated: bool = True
    def payload(self):
        return {'source_ref':self.ref,'text':self.text,'authenticated':self.authenticated,'sha256':digest(self.text)}

# Canonical machine-readable carrier grammar, used ONLY by deterministic baselines and fixtures.
# It is not an LLM mock and does not claim general natural-language extraction.
FIELDS=['constraint_id','entity','scope','parameter','value','unit','conversion','aggregation','valid_from','valid_to','precedence']

def render_templates(constraints: list[Constraint], variant: int=0) -> list[SourceDocument]:
    docs=[]
    for c in constraints:
        conv='none' if c.conversion is None else str(c.conversion)
        body=f"RULE {c.constraint_id} | {c.entity} | {c.scope} | {c.parameter} | {c.value} | {c.unit} | {conv} | {c.aggregation} | {c.valid_from} | {c.valid_to} | {c.precedence}"
        if variant%2:
            note=f"For {c.entity}, {c.parameter.replace('_',' ')} is {c.value} {c.unit}. This rule applies from day {c.valid_from} through {c.valid_to}, inclusive."
        else:
            note=f"Contract clause: {c.entity} must comply with {c.parameter} = {c.value} {c.unit}; scope {c.scope}."
        docs.append(SourceDocument(c.source_ref,note+'\n'+body))
    return docs

def render_prose(constraints: list[Constraint], variant: int=0) -> list[SourceDocument]:
    """Field-complete prose WITHOUT the RULE carrier: every field the schema needs is stated once, in words. The
    deterministic parser cannot read it and escalates, so a run on this carrier measures what a configured model adds.
    Two phrasings alternate by day so that the model never sees one fixed template."""
    docs=[]
    for c in constraints:
        conv='none' if c.conversion is None else str(c.conversion)
        if variant%2:
            text=(f"Rule {c.constraint_id}. For entity {c.entity}, scope {c.scope}, {c.parameter} is {c.value} {c.unit}. "
                  f"Aggregation level: {c.aggregation}. Effective from day {c.valid_from} to day {c.valid_to}, both inclusive. "
                  f"Precedence {c.precedence}. Conversion: {conv}.")
        else:
            text=(f"Contract clause {c.constraint_id} (precedence {c.precedence}, aggregation {c.aggregation}): {c.entity} "
                  f"must comply with {c.parameter} = {c.value} {c.unit} at {c.scope} scope, valid from day {c.valid_from} "
                  f"to day {c.valid_to} inclusive; conversion {conv}.")
        docs.append(SourceDocument(c.source_ref,text))
    return docs

def extract_templates(documents: list[SourceDocument], lineage: Lineage) -> ConstraintSet:
    constraints=[];issues=[]
    for doc in documents:
        if not doc.authenticated: issues.append(f'unauthenticated source {doc.ref}');continue
        if screen_injection(doc.text): issues.append(f'injection screening flagged {doc.ref}');continue
        found=False
        for line in doc.text.splitlines():
            if not line.startswith('RULE '): continue
            found=True; vals=[x.strip() for x in line[5:].split('|')]
            if len(vals)!=len(FIELDS): issues.append(f'malformed template {doc.ref}');continue
            obj=dict(zip(FIELDS,vals))
            obj.update(source_ref=doc.ref,confidence=1.0,conversion=None if obj['conversion']=='none' else float(obj['conversion']))
            try: constraints.append(Constraint.model_validate(obj))
            except ValueError as exc: issues.append(f'invalid constraint {doc.ref}: {exc}')
        if not found: issues.append(f'no recognized deterministic rule in {doc.ref}')
    return ConstraintSet(lineage=lineage,constraints=constraints,issues=issues)

def verify_constraints(cs: ConstraintSet, series: list[Series], documents: list[SourceDocument], day: int,
                       confidence_threshold: float=0.9) -> ConstraintSet:
    issues=list(cs.issues);active=[];seen={}
    refs={d.ref:d for d in documents}
    entities={'portfolio'}|{s.series_id for s in series}|{s.item_id for s in series}|{s.supplier for s in series}|{s.cluster for s in series}
    units={'pack':{'unit'},'moq':{'unit'},'aggregate_moq':{'unit','m'},'capacity':{'unit'},
           'lead_time':{'day'},'unit_cost':{'USD/unit'},'fixed_cost':{'USD'},'budget':{'USD'},
           'eligibility':{'bool'},'conversion':{'m/unit'},'storage':{'unit'}}
    for c in cs.constraints:
        if not c.valid_from<=day<=c.valid_to: continue
        if c.entity not in entities: issues.append(f'{c.constraint_id}: unknown entity {c.entity}')
        if c.source_ref not in refs or not refs[c.source_ref].authenticated:
            issues.append(f'{c.constraint_id}: untrusted/missing source')
        elif screen_injection(refs[c.source_ref].text): issues.append(f'{c.constraint_id}: input instruction detected')
        if c.unit not in units[c.parameter]: issues.append(f'{c.constraint_id}: dimensional mismatch {c.unit}')
        if c.value<0 or (c.parameter in {'pack','lead_time','conversion','unit_cost'} and c.value<=0): issues.append(f'{c.constraint_id}: invalid range')
        if c.parameter in {'pack','moq','lead_time','eligibility'} and c.value!=int(c.value): issues.append(f'{c.constraint_id}: noninteger discrete parameter')
        if c.parameter=='eligibility' and c.value not in {0,1}: issues.append(f'{c.constraint_id}: eligibility is not binary')
        if c.confidence<confidence_threshold: issues.append(f'{c.constraint_id}: low extraction confidence')
        if c.conversion is not None and c.conversion<=0: issues.append(f'{c.constraint_id}: invalid conversion')
        key=(c.entity,c.parameter)
        if key in seen:
            old=seen[key]
            if old.precedence==c.precedence and (old.value,old.unit,old.conversion)!=(c.value,c.unit,c.conversion):
                issues.append(f'{c.constraint_id}: conflicting equal-precedence rules')
            elif c.precedence>old.precedence: seen[key]=c
        else: seen[key]=c
    active=list(seen.values())
    for document in documents:
        if not any(line.startswith('RULE ') for line in document.text.splitlines()):continue
        expected=extract_templates([document],cs.lineage)
        for rule in expected.constraints:
            if not rule.valid_from<=day<=rule.valid_to:continue
            candidates=[c for c in cs.constraints if c.source_ref==document.ref and c.entity==rule.entity and c.parameter==rule.parameter]
            fields=['value','unit','conversion','scope','aggregation','valid_from','valid_to','precedence']
            if not candidates:issues.append(f'{rule.constraint_id}: recognized source rule omitted')
            elif not any(all(getattr(c,f)==getattr(rule,f) for f in fields) for c in candidates):
                issues.append(f'{rule.constraint_id}: extraction conflicts with deterministic source template')
    # A meter-valued minimum needs EVERY member's meter-per-order-unit conversion.
    by_key={(c.entity,c.parameter):c for c in active}
    for c in active:
        if c.parameter=='aggregate_moq' and c.unit=='m':
            for s in series:
                if s.supplier==c.entity and (s.series_id,'conversion') not in by_key and (s.item_id,'conversion') not in by_key:
                    issues.append(f'{c.constraint_id}: missing m/unit consumption for {s.series_id}')
    for s in series:
        for param in ['pack','moq','unit_cost','lead_time','eligibility']:
            if not any((key,param) in by_key for key in [s.series_id,s.item_id,s.supplier]):
                issues.append(f'{s.series_id}: missing required {param}')
    return ConstraintSet(lineage=cs.lineage,constraints=active,issues=sorted(set(issues)))

def lookup(cs: ConstraintSet, s: Series | None, parameter: str, default: float | None=None) -> float:
    targets=[s.series_id,s.item_id,s.supplier,'portfolio'] if s else ['portfolio']
    for target in targets:
        matches=[c for c in cs.constraints if c.entity==target and c.parameter==parameter]
        if matches: return max(matches,key=lambda x:x.precedence).value
    if default is None: raise ValueError(f'Missing {parameter} for {s.series_id if s else "portfolio"}')
    return default

def synthetic_contracts(series: list[Series], prices: list[float], eligible: list[bool], day: int, seed: int,
                        scenario: str, shock: bool, budget: float) -> list[Constraint]:
    result=[]
    def add(entity,scope,parameter,value,unit,aggregation='line'):
        cid=f'{entity}:{parameter}:{day}'
        result.append(Constraint(constraint_id=cid,entity=entity,scope=scope,parameter=parameter,value=float(value),unit=unit,
                      aggregation=aggregation,valid_from=day,valid_to=day,precedence=10,source_ref=f'contract/{cid}',confidence=1.0))
    for i,s in enumerate(series):
        rng=keyed_rng(seed,'contracts',s.item_id);pack=int(rng.choice([1,2,6]));lead=int(rng.choice([2,3,4]))
        if scenario=='pack_change' and shock: pack*=2
        if scenario=='lead_time_shift' and shock: lead+=3
        add(s.series_id,'series','pack',pack,'unit')
        add(s.series_id,'series','moq',pack,'unit')
        # Unknown prices remain a state failure; this documented supplier-cost default is synthetic.
        price=prices[i] if np.isfinite(prices[i]) and prices[i]>0 else 5.0
        add(s.series_id,'series','unit_cost',price*0.55,'USD/unit')
        add(s.series_id,'series','lead_time',lead,'day')
        e=eligible[i]
        if scenario in {'eligibility_change','season_end'} and shock and i%3==0: e=False
        add(s.series_id,'series','eligibility',int(e),'bool')
        if scenario=='foreign_unit_moq': add(s.series_id,'series','conversion',1.2+(i%3)*0.2,'m/unit')
    for supplier in sorted({s.supplier for s in series}):
        size=sum(s.supplier==supplier for s in series)
        capacity=100*size
        if scenario=='capacity_cut' and shock: capacity*=0.4
        if scenario=='supplier_failure' and shock and supplier==sorted({s.supplier for s in series})[0]: capacity=0
        add(supplier,'supplier','capacity',capacity,'unit','supplier_order')
        add(supplier,'supplier','fixed_cost',2,'USD','supplier_order')
        if scenario in {'aggregate_moq','foreign_unit_moq'}:
            add(supplier,'supplier','aggregate_moq',12*size,'m' if scenario=='foreign_unit_moq' else 'unit','supplier_order')
    add('portfolio','portfolio','budget',budget,'USD','portfolio')
    return result
