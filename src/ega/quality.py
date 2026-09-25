"""Deterministic evidence checks. No check receives perturbation labels or oracle state."""
from __future__ import annotations
from collections import Counter
import numpy as np
from .schemas import Snapshot, Check, Certificate
from .config import GateConfig
from .util import digest

def certify(snapshot: Snapshot, config: GateConfig) -> Certificate:
    checks=[]
    def add(name,family,outcome,evidence,weight=0.12):
        checks.append(Check(name=name,family=family,outcome=outcome,evidence=evidence,weight=weight))
    ids=[s.series_id for s in snapshot.series];expected=set(ids)
    actual=[r.series_id for r in snapshot.inventory]
    ages={table:snapshot.lineage.day-day for table,day in snapshot.stage_days.items()}
    max_age=max(ages.values(),default=999)
    add('table_freshness','feed_gap','hard_fail' if max_age>config.max_feed_age else ('warn' if max_age>0 else 'pass'),{'ages_days':ages},0.2)
    dates=snapshot.history_days
    gaps=sorted(set(range(min(dates),snapshot.lineage.day))-set(dates)) if dates else [snapshot.lineage.day-1]
    missing=sum(v is None for row in snapshot.history for v in row)
    add('history_continuity','feed_gap','warn' if gaps or missing else 'pass',{'missing_days':gaps,'missing_values':missing},0.2)
    spread=max(ages.values())-min(ages.values()) if ages else 999
    add('partial_refresh','partial_refresh','hard_fail' if spread>config.max_feed_age else ('warn' if spread else 'pass'),{'age_spread':spread},0.15)
    now_hash=digest(sorted([(r.series_id,r.quantity) for r in snapshot.inventory]))
    frozen=now_hash==snapshot.previous_inventory_hash and snapshot.movement_volume>0
    add('content_reuse','stale_but_fresh','warn' if frozen else 'pass',{'hash_equal':now_hash==snapshot.previous_inventory_hash,'movement_volume':snapshot.movement_volume},0.35)
    duplicates=[k for k,v in Counter(actual).items() if v>1]
    po_dupes=[k for k,v in Counter(p.order_id for p in snapshot.open_orders).items() if v>1]
    sales_dupes=[k for k,v in Counter(x.key for x in snapshot.sales_lines).items() if v>1]
    add('unique_keys','duplicate_ingestion','hard_fail' if duplicates or po_dupes or sales_dupes else 'pass',{'inventory':duplicates,'open_orders':po_dupes,'sales':sales_dupes})
    missing_ids=sorted(expected-set(actual));unknown_ids=sorted(set(actual)-expected)
    add('expected_pairs','orphaned_facts','hard_fail' if missing_ids or unknown_ids else 'pass',{'missing':missing_ids,'unknown':unknown_ids})
    locations=set(snapshot.source_locations)-set(snapshot.loaded_locations)
    add('source_location_reconciliation','unmapped_location','hard_fail' if locations else 'pass',{'unmapped':sorted(locations)})
    count_mismatch=snapshot.source_row_count != len(actual)
    add('source_load_counts','orphaned_facts','warn' if count_mismatch else 'pass',{'source':snapshot.source_row_count,'loaded':len(actual)})
    bad=[]
    for row in snapshot.inventory:
        if row.quantity<0 or row.unit!='unit':bad.append(row.series_id)
        if row.source_quantity is not None and abs(row.quantity-row.source_quantity)>max(1,abs(row.source_quantity)*0.05):bad.append(row.series_id)
    for row in snapshot.sales_lines:
        if row.quantity<0 or row.unit_price<0 or abs(row.line_total-row.quantity*row.unit_price)>max(0.02,0.01*abs(row.line_total)):
            bad.append(row.key)
    add('unit_range_and_ratio','unit_inflation','hard_fail' if bad else 'pass',{'records':sorted(set(bad))})
    currencies={s.series_id:s.currency for s in snapshot.series}
    wrong_currency=[x.key for x in snapshot.sales_lines if x.currency!=currencies.get(x.series_id)]
    bad_prices=[ids[i] for i,p in enumerate(snapshot.prices) if p<=0]
    add('currency_and_price_coverage','currency_mislabel','hard_fail' if wrong_currency or bad_prices else 'pass',{'wrong_currency':wrong_currency,'missing_prices':bad_prices})
    alias_bad=[s.supplier for s in snapshot.series if s.supplier in snapshot.aliases and snapshot.aliases[s.supplier]!=s.supplier]
    add('identity_aliases','identity_drift','warn' if alias_bad else 'pass',{'unresolved_aliases':alias_bad},0.35)
    placeholders=[s.series_id for s in snapshot.series if not s.attributes_complete]
    add('master_attributes','placeholder_master','hard_fail' if placeholders else 'pass',{'placeholders':placeholders})
    po_hard=[];po_warn=[]
    suppliers={s.supplier for s in snapshot.series}
    for po in snapshot.open_orders:
        if po.quantity<0 or not po.stock_line or po.supplier not in suppliers or po.series_id not in expected:
            po_hard.append(po.order_id)
        if po.ordered_day is None or po.due_day is None:po_warn.append(po.order_id)
        if po.ordered_day is not None and po.due_day is not None and po.due_day<po.ordered_day:po_hard.append(po.order_id)
    add('purchase_order_integrity','open_order_integrity','hard_fail' if po_hard else ('warn' if po_warn else 'pass'),{'invalid':po_hard,'unknown_dates':po_warn},0.16)
    movement=[]
    for row in snapshot.inventory:
        exp=snapshot.expected_inventory.get(row.series_id)
        if exp is not None and abs(row.quantity-exp)>max(2,0.1*abs(exp)):
            movement.append({'series_id':row.series_id,'observed':row.quantity,'ledger_expected':exp})
    add('stock_movement_balance','movement','hard_fail' if movement else 'pass',{'mismatches':movement})
    prev_total=sum(snapshot.previous_inventory.values()); total=sum(r.quantity for r in snapshot.inventory)
    collapse=prev_total>10 and total<0.15*prev_total and bool(movement)
    add('inventory_distribution_shift','derived_field_collapse','hard_fail' if collapse else 'pass',{'previous_total':prev_total,'current_total':total,'movement_inconsistent':bool(movement)})
    add('historical_snapshot_diff','historical_restatement','warn' if snapshot.history_revision>0.05 else 'pass',{'relative_revision':snapshot.history_revision},0.25)
    censored=sum(sum(row) for row in snapshot.stockout_flags)
    add('stockout_flags','censored_demand','warn' if censored else 'pass',{'flagged_history_cells':censored},0.04)
    quality=0.0 if any(c.outcome=='hard_fail' for c in checks) else max(0.0,1-sum(c.weight for c in checks if c.outcome=='warn'))
    # Certificate refers to its input lineage; downstream lineage carries this certificate's hash.
    return Certificate(lineage=snapshot.lineage.model_copy(deep=True),quality=quality,checks=checks)
