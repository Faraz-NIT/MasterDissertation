"""Versioned disturbance operators and common-random-number schedules."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass
import numpy as np
from .schemas import Snapshot
from .config import QualityLayerConfig
from .util import keyed_rng, digest

QUALITY_CLASSES=['feed_gap','partial_refresh','stale_but_fresh','duplicate_ingestion','unit_inflation',
                 'currency_mislabel','unmapped_location','identity_drift','placeholder_master',
                 'orphaned_facts','open_order_integrity','historical_restatement','derived_field_collapse']
SCENARIOS=['normal','mixed_quality',*QUALITY_CLASSES,'censored_demand','promotion_spike','lead_time_shift',
           'capacity_cut','supplier_failure','heavy_tail_demand','pack_change','aggregate_moq',
           'foreign_unit_moq','eligibility_change','season_end','injection','transshipment']

@dataclass(frozen=True)
class Fault:
    family: str
    onset: int
    duration: int
    magnitude: float

class FaultSchedule:
    def __init__(self, scenario: str, start: int, days: int, seed: int, config: QualityLayerConfig):
        if scenario not in SCENARIOS:raise ValueError(f'Unknown scenario {scenario}')
        self.events=[]
        calibration={}
        if config.calibrated:
            calibration=json.loads(Path(config.calibration_file).read_text())
            if not calibration.get('pooled_anonymized') or not calibration.get('provenance'):
                raise ValueError('Calibration file needs pooled_anonymized=true and provenance')
        if scenario in QUALITY_CLASSES:
            self.events=[Fault(scenario,start+max(1,days//3),min(config.max_duration,max(1,days//2)),config.magnitude)]
        elif scenario=='mixed_quality':
            for family in QUALITY_CLASSES:
                next_possible=start
                for d in range(start,start+days):
                    if d<next_possible:continue
                    rng=keyed_rng(seed,'fault-onset',family,d)
                    entry=calibration.get('classes',{}).get(family,{})
                    if config.calibrated and (not entry or entry.get('rare_event_only',False)):continue
                    rate=entry.get('onset_rate_range',[config.onset_rate,config.onset_rate])
                    p=float(rng.uniform(*rate))*config.rate_multiplier
                    if rng.random()<min(1,p):
                        limits=entry.get('duration_range',[config.min_duration,config.max_duration])
                        duration=int(rng.integers(limits[0],limits[1]+1))
                        self.events.append(Fault(family,d,duration,config.magnitude));next_possible=d+duration
    def active(self,day:int)->list[Fault]:
        return [e for e in self.events if e.onset<=day<e.onset+e.duration]

def perturb(snapshot: Snapshot, previous: Snapshot | None, faults: list[Fault]) -> Snapshot:
    obs=snapshot.model_copy(deep=True)
    for fault in faults:
        f=fault.family;age=snapshot.lineage.day-fault.onset+1
        if f=='feed_gap':
            if previous is not None:
                obs.inventory=[r.model_copy(deep=True) for r in previous.inventory]
                obs.open_orders=[r.model_copy(deep=True) for r in previous.open_orders]
            for k in obs.stage_days:obs.stage_days[k]=snapshot.lineage.day-age
            if obs.history_days:
                for row in obs.history:row[-1]=None
        elif f=='partial_refresh':
            if previous:obs.inventory=[r.model_copy(deep=True) for r in previous.inventory]
            obs.stage_days['inventory']=snapshot.lineage.day-age-1
        elif f=='stale_but_fresh':
            if previous:
                obs.inventory=[r.model_copy(deep=True) for r in previous.inventory]
                obs.previous_inventory_hash=digest(sorted([(r.series_id,r.quantity) for r in previous.inventory]))
        elif f=='duplicate_ingestion':
            obs.inventory += [r.model_copy(deep=True) for r in obs.inventory]
            obs.open_orders += [r.model_copy(deep=True) for r in obs.open_orders]
            obs.sales_lines += [r.model_copy(deep=True) for r in obs.sales_lines]
            obs.history=[[None if v is None else v*2 for v in row] for row in obs.history]
        elif f=='unit_inflation':
            for row in obs.inventory:row.quantity*=max(2,fault.magnitude)
            for row in obs.sales_lines:row.quantity*=max(2,fault.magnitude)
        elif f=='currency_mislabel':
            for row in obs.sales_lines:row.currency='EUR'
        elif f=='unmapped_location':
            loc=obs.series[0].location
            obs.loaded_locations=[x for x in obs.loaded_locations if x!=loc]
            hidden={s.series_id for s in obs.series if s.location==loc}
            obs.inventory=[r for r in obs.inventory if r.series_id not in hidden]
            obs.operator_notes.append(f'Source manifest contains location {loc}; location-master stage did not resolve its key.')
        elif f=='identity_drift':
            original=obs.series[0].supplier;alias=original.lower()+' '
            for s in obs.series:
                if s.supplier==original:s.supplier=alias
            obs.aliases[alias]=original
        elif f=='placeholder_master':obs.series[0].attributes_complete=False
        elif f=='orphaned_facts':obs.inventory=obs.inventory[1:]
        elif f=='open_order_integrity':
            for po in obs.open_orders:po.supplier=None;po.due_day=None
        elif f=='historical_restatement':
            for row in obs.history:
                for j in range(max(0,len(row)-14),len(row)-1):
                    if row[j] is not None:row[j]*=0.5
            obs.history_revision=0.5;obs.operator_notes.append('Historical sales rows were revised by the upstream rolling-window export; business reason is unconfirmed.')
        elif f=='derived_field_collapse':
            for row in obs.inventory:row.quantity=0
    return obs

def demand_for_day(base: np.ndarray, day: int, start: int, length: int, scenario: str, seed: int) -> np.ndarray:
    values=base.astype(float).copy();shock=day>=start+max(1,length//3)
    if shock and scenario=='promotion_spike':values*=2.5
    if scenario=='heavy_tail_demand':
        for i in range(len(values)):
            rng=keyed_rng(seed,'demand',day,i)
            if rng.random()<0.04:values[i]*=float(1+rng.pareto(2.2)*3)
    return np.maximum(0,np.rint(values))
