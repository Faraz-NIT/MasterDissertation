"""Execute the frozen 30-seed study; no inventory repair, retries or LLM cache."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (ARMS, EXAMPLES, MODEL, OUT, PROMPTS, ROOT, SCENARIOS, Inventory, Ollama,
                  checks, constrained_order, contracts, conventional_order,
                  dump, rng, sha, supplier_message, verify_source)


def now():
    return datetime.now(timezone.utc).isoformat()


def load(dataset,origin=None):
    folder = OUT/"data"/dataset
    if origin is not None: folder = folder/f"origin_{origin}"
    data = json.loads((folder/"catalog.json").read_text())
    with np.load(folder/"panel_and_forecast.npz") as arrays:
        data.update({k: arrays[k] for k in arrays.files})
    return data


def audit(stage, payload):
    path = OUT/"workflow.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps({"at_utc": now(), "stage": stage, "payload": payload}, allow_nan=False)+"\n")
        stream.flush()


def develop():
    development = OUT/"development"
    round_number = 1 + len(list(development.glob("round_*")))
    folder = development/f"round_{round_number:02d}"
    folder.mkdir(exist_ok=False)
    client = Ollama(folder/"calls")
    checks_done = []
    for dataset in ("M5", "RetailNet"):
        data = load(dataset)
        for style, scenario in enumerate(SCENARIOS):
            rules = contracts(data, scenario, 901, 3)
            name = dataset+"_"+scenario
            message = supplier_message(rules, 3, style)
            answer = client.ask("supplier", message, name)
            valid, slots, failures = verify_source(answer, rules)
            checks_done.append({"case":name,"test":"supplier_extraction","pass":valid,"correct_slots":slots,"failures":failures})
        for scenario in ("routine", "promotion"):
            answer = client.ask("planner", f"Scenario: {scenario}. Active promotion: {scenario == 'promotion'}. Current stock 300. Forecast 160. Verified rules available.",dataset+"_"+scenario)
            expected = "service_first" if scenario == "promotion" else "balanced"
            checks_done.append({"case":dataset+"_"+scenario,"test":"tool_routing","pass":bool(answer and answer["tool"]=="constrained_order" and answer["priority"]==expected)})
        for status in ("pass", "fail"):
            answer = client.ask("critic", json.dumps({"source_verification":"pass","tool_routing":"pass","solver_feasible":True,"action_checks":{"pack":"pass","moq":"pass","capacity":"pass","budget":status}}), dataset+"_critic_"+status)
            expected = "approve" if status=="pass" else "hold"
            checks_done.append({"case":dataset+"_"+status,"test":"critic","pass":bool(answer and answer["verdict"]==expected)})
    result = {"status":"PASS" if all(t["pass"] for t in checks_done) else "FAIL",
              "at_utc":now(),"cases":checks_done,"calls":client.records,
              "primary_evaluation_outcomes_consulted":False,
              "note":"Development uses training-derived contract scales and invented operational snapshots; not result data."}
    dump(folder/"smoke_receipt.json", result)
    dump(development/"smoke_receipt.json",result)
    audit("development_complete", {"status":result["status"],"fresh_calls":len(client.records)})
    print(json.dumps({"status":result["status"],"calls":len(client.records),"failures":[t for t in checks_done if not t["pass"]]}),flush=True)
    if result["status"] != "PASS":
        raise RuntimeError("Resolve development failures before freezing")


def freeze():
    path = OUT/"protocol.json"
    if path.exists():
        raise FileExistsError("Protocol already frozen")
    assert json.loads((OUT/"development/smoke_receipt.json").read_text())["status"] == "PASS"
    assert json.loads((OUT/"development/numerical_tests.json").read_text())["status"] == "PASS"
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as response:
        model = next(m for m in json.load(response)["models"] if m["name"] == MODEL)
    with urllib.request.urlopen("http://127.0.0.1:11434/api/version",timeout=10) as response:
        ollama_version = json.load(response)
    started = datetime.fromisoformat("2026-10-08T22:18:08+00:00")
    files = [ROOT/"scripts/ollama_clean_study"/name for name in ("core.py","prepare.py","run.py")]
    frozen = OUT/"frozen_code"
    frozen.mkdir(exist_ok=False)
    for file in files:
        shutil.copyfile(file,frozen/file.name)
    datasets = {}
    for dataset in ("M5","RetailNet"):
        data = load(dataset)
        origins = [data["origin"]-7,data["origin"]]
        datasets[dataset] = {"series":30,"origins":origins,"days_per_origin":7,
            "evaluation_dates":{str(o):data["dates"][o:o+7] for o in origins},
            "file_sha256":{str(p.relative_to(OUT/"data"/dataset)):sha(p) for p in (OUT/"data"/dataset).rglob('*') if p.is_file()}}
    protocol = {
        "schema":"ollama-clean-study-v1","status":"FROZEN","frozen_at_utc":now(),
        "requested_at_utc":started.isoformat(),
        "experiment_cutoff_utc":(started+timedelta(hours=3,minutes=55)).isoformat(),
        "report_and_publication_target_utc":(started+timedelta(hours=4,minutes=45)).isoformat(),
        "user_timezone":"Europe/Paris",
        "question":"Can a small local LLM multi-agent workflow deliver reliable replenishment, and what does it add beyond its numerical planning tool?",
        "datasets":datasets,"arms":{
            "conventional":"Order-up-to with proportionate capacity/budget allocation; current structured rules; aggregate inventory position, no age projection",
            "structured_planner":"Same constrained-order tool, age projection and scenario-priority mapping as the agents; authoritative structured rules; no LLM",
            "llm_agents":"Three separate Ollama calls: supplier reader, tool coordinator, independent review; current supplier prose; source verification; same planning tool"},
        "scenarios":SCENARIOS,"simulation_seeds":list(range(101,131)),"joint_series_per_decision":30,
        "expected_runs":1080,"expected_portfolio_days":7560,"expected_llm_portfolio_days":2520,
        "expected_primary_fresh_model_calls":7560,
        "no_inventory_repairs":True,"no_data_fault_injections":True,"no_sales_recovery_or_imputation":True,
        "no_prior_outputs_loaded":True,"llm_response_cache":False,"llm_retries":0,"fallback_on_failure":"Hold, never replace LLM output with baseline output",
        "shared_forecast":{"family":"LightGBM regression","trees":150,"one_model_per_dataset_and_origin":True,
            "training":"Past-only panel, at most 365 days; recursive 14-day prediction; no evaluation outcomes as model inputs",
            "uncertainty":"Standard deviation of training weekly sales differences / sqrt(2); not evaluation residuals"},
        "model":{"tag":MODEL,"digest":model["digest"],"details":model["details"],"ollama":ollama_version,
            "temperature":0,"generation_seed":20261009,"threads":3,"context":4096,"output_limit":512,
            "retail_fine_tuning":False,"inference_only":True,"host":"127.0.0.1:11434","cloud_llm_api_used":False},
        "environment":{"os":platform.platform(),"cpu_quota":Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
            "memory_limit_bytes":int(Path('/sys/fs/cgroup/memory.max').read_text()),"gpu":False,
            "packages":{p:version(p) for p in ('numpy','pandas','scipy','lightgbm','pyarrow','jsonschema')}},
        "simulation":{"initial_stock":"ceil(3 * past-56-day mean); no initial pipeline; common per matched case",
            "demand":"Published evaluation sales proxy times independent mean-one lognormal factor (sigma=.10); promotion multiplies day 2 onward by 1.3",
            "promotion_knowledge":"Announced multiplier is available equally before affected decisions; no realised future demand shown",
            "supplier_disruption":"Day 2 onward: double cartons and MOQ, add one delivery day, reduce capacity 30%; current terms available equally",
            "suppliers":"Three synthetic groups, ten series each; not publisher supplier observations",
            "budget_and_capacity":"Training-derived 2.8x historical mean; current daily +/-8% announced variation; unit purchase cost 1",
            "supply":"Opportunity-keyed: 2% cancellation, 10% 80% fill, 10% extra-day delay; same draws for matched arms",
            "shelf_life":"M5 nonperishable within horizon; RetailNet hypothetical 3-day FIFO",
            "planning":"Standard policy z=1.28. Tool z=1.28 balanced or 1.65 for promotion; MILP minimises purchase + weighted target shortfall, with hard budget/capacity/pack/MOQ limits",
            "primary_cost":"Inventory operating cost index = .02 * closing stock + 5 * unmet demand + expired units, summed over seven days",
            "purchase_spend":"Reported separately; not added to primary operating cost to avoid double-counting acquisition and expiry",
            "economics":"Synthetic dimensionless cost index; not retailer profit or real monetary ROI"},
        "primary_measures":["fill rate","inventory operating cost index per unit demand","expiry share of opening inventory + receipts","constraint violations","holds"],
        "llm_measures":["Exact supplier fields (13 per call)","correct business-priority selection","critic decisions","schema validity","latency","tokens"],
        "inference":"Paired simulation-seed bootstrap (10,000 resamples), with origins averaged within seed; seeds describe simulated demand/supply variation conditional on selected historical weeks, not population or independent model replications",
        "time_rule":"Process seeds in balanced rounds across both datasets and all scenarios. Start no new case after cutoff; retain and label partial cases. Never conceal missing runs.",
        "limitations":["30 selected series per dataset, not all 50K RetailNet series","Two historical test weeks per dataset; RetailNet includes one rolling training-file holdout and the official evaluation week",
            "Historical evaluation periods were used in earlier work; fresh execution does not make them unseen research holdouts",
            "Controlled supplier messages, simulated inventories and supply; no retailer deployment or measured staff time",
            "Structured planner is a strong idealised comparator with already-structured current rules; manual entry time not measured",
            "Any advantage over conventional ordering can include the numerical tool; the structured comparator isolates that contribution",
            "Source verification compares LLM extraction with authenticated current contract fields; those fields contain no future demand",
            "One small deterministic pretrained LLM; no generalisation to other models claimed"],
        "prompts":PROMPTS,"few_shot_examples":EXAMPLES,"code_sha256":{str(p.relative_to(ROOT)):sha(p) for p in files},
        "source_commit":subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    }
    dump(path,protocol)
    audit("protocol_frozen",{"sha256":sha(path),"runs":1080,"fresh_calls":7560})
    print(json.dumps({"status":"FROZEN","sha256":sha(path),"expected_runs":1080,"expected_fresh_calls":7560}),flush=True)


def verify():
    p = json.loads((OUT/"protocol.json").read_text())
    assert p["status"] == "FROZEN"
    for rel, expected in p["code_sha256"].items():
        assert sha(ROOT/rel) == expected, rel
    for dataset, info in p["datasets"].items():
        for file, expected in info["file_sha256"].items():
            assert sha(OUT/"data"/dataset/file) == expected
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=10) as response:
        current = next(m for m in json.load(response)["models"] if m["name"]==MODEL)
    assert current["digest"] == p["model"]["digest"]
    return p


def run_case(data, scenario, seed):
    dataset = data["dataset"]
    origin = data["origin"]
    case = f"{dataset}__{scenario}__seed{seed}__origin{origin}"
    root = OUT/"runs"/case
    if root.exists():
        raise FileExistsError("Never overwrite an existing run case: "+case)
    root.mkdir(parents=True)
    inventory = {arm:Inventory(data,seed) for arm in ARMS}
    client = Ollama(root/"model_calls")
    daily = {arm:[] for arm in ARMS}
    started = time.perf_counter()
    truth_demand = data["sales"][:,data["origin"]:data["origin"]+7].copy()
    factors = rng(seed,"demand",dataset).lognormal(-.5*.1**2,.1,size=truth_demand.shape)
    truth_demand *= factors
    if scenario == "promotion": truth_demand[:,2:] *= 1.3
    dump(root/"demand_world.json",{"quantities":truth_demand.tolist(),"seed":seed,"agents_received_this_file":False})
    with (root/"decisions.jsonl").open("w") as decisions:
        for day in range(7):
            rules = contracts(data,scenario,seed,day)
            message = supplier_message(rules,day,(seed+day)%3)
            active_promotion = scenario == "promotion" and day >= 2
            priority = "service_first" if active_promotion else "balanced"
            forecast = data["forecast"].copy()
            if active_promotion: forecast[:,day:] *= 1.3
            for arm in ARMS:
                env = inventory[arm]; env.begin(day)
                before_stock = env.stock().copy()
                before_pipeline = [p.copy() for p in env.pending]
                count_before = len(client.records)
                source_ok, slots, source_failures = True, 13, []
                chosen_priority = "balanced" if arm=="conventional" else priority
                route_ok = True
                model_outputs = {}
                wall_start = time.perf_counter()
                if arm=="llm_agents":
                    extracted = client.ask("supplier",message,f"day{day}")
                    model_outputs["supplier"] = extracted
                    source_ok,slots,source_failures = verify_source(extracted,rules)
                    context = {"scenario":scenario,"active_promotion":active_promotion,
                        "inventory_units":round(float(before_stock.sum()),2),
                        "forecast_today":round(float(forecast[:,day].sum()),2),
                        "current_budget":rules["budget"],"source_verification":"pass" if source_ok else "fail",
                        "supplier_rules":extracted}
                    coordination = client.ask("planner",json.dumps(context),f"day{day}")
                    model_outputs["planner"] = coordination
                    route_ok = bool(coordination and coordination.get("tool")=="constrained_order")
                    chosen_priority = coordination["priority"] if coordination else "balanced"
                target,urgency = env.target(forecast,data["residual_sd"],day,rules,data["groups"],chosen_priority,arm!="conventional")
                if not source_ok or not route_ok:
                    proposed = np.zeros(30); solver={"feasible":False,"reason":"source_or_route_failed"}
                elif arm=="conventional":
                    proposed,solver = conventional_order(target,rules,data["groups"])
                else:
                    # Exact-source validation succeeded; the extracted current values equal these authenticated fields.
                    proposed,solver = constrained_order(target,urgency,rules,data["groups"])
                failures = checks(proposed,rules,data["groups"])
                valid = source_ok and route_ok and solver["feasible"] and not failures
                critic_approved = True
                if arm=="llm_agents":
                    review_context = {"source_verification":"pass" if source_ok else "fail",
                        "tool_routing":"pass" if route_ok else "fail","solver_feasible":bool(solver["feasible"]),
                        "action_checks":{"pack":"fail" if "pack_size" in failures else "pass",
                            "moq":"fail" if "minimum_order" in failures else "pass",
                            "capacity":"fail" if any(x.startswith("capacity") for x in failures) else "pass",
                            "budget":"fail" if "budget" in failures else "pass",
                            "nonnegative":"fail" if "nonnegative_quantities" in failures else "pass"},
                        "proposed_units":int(proposed.sum()),"budget":rules["budget"]}
                    review = client.ask("critic",json.dumps(review_context),f"day{day}")
                    model_outputs["critic"] = review
                    critic_approved = bool(review and review["verdict"]=="approve")
                permitted = bool(valid and critic_approved)
                committed = proposed if permitted else np.zeros(30)
                true_failures = checks(committed,rules,data["groups"])
                if true_failures: raise AssertionError("Execution gate permitted a violated rule")
                purchase = env.execute(day,committed,rules,data["groups"]) if permitted else 0.0
                outcome = env.end(day,truth_demand[:,day])
                calls = client.records[count_before:]
                row = {"dataset":dataset,"scenario":scenario,"seed":seed,"origin":origin,"day":day,"arm":arm,
                    "held":int(not permitted),"orders":float(committed.sum()),"purchase_spend":purchase,
                    "actual_violations":len(true_failures),"source_correct_slots":slots,
                    "source_exact":int(source_ok),"priority_correct":int(chosen_priority==priority),
                    "critic_should_approve":int(valid),"critic_approved":int(critic_approved),
                    "critic_false_approval":int(not valid and critic_approved),
                    "critic_false_hold":int(valid and not critic_approved),
                    "model_calls":len(calls),"schema_failures":sum(not c["schema_valid"] for c in calls),
                    "input_tokens":sum(c["input_tokens"] for c in calls),"output_tokens":sum(c["output_tokens"] for c in calls),
                    "agent_seconds":time.perf_counter()-wall_start,
                    **{k:v for k,v in outcome.items() if not isinstance(v,list)}}
                daily[arm].append(row)
                record = {"row":row,"stock_before":before_stock.tolist(),"pending_before":before_pipeline,
                    "batches_after":env.batches,"source_text":message,"authoritative_contract":rules,
                    "source_verification_failures":source_failures,"chosen_priority":chosen_priority,
                    "expected_priority":priority,"model_outputs":model_outputs,"forecast_today":forecast[:,day].tolist(),
                    "target_gap":target.tolist(),"urgency":urgency.tolist(),"solver":solver,
                    "proposed":proposed.tolist(),"committed":committed.tolist(),"action_checks":failures,
                    "outcome":outcome,"model_call_records":calls}
                decisions.write(json.dumps(record,allow_nan=False)+"\n");decisions.flush()
            dump(OUT/"progress.json",{"status":"RUNNING","at_utc":now(),"case":case,"day_completed":day,
                "elapsed_case_seconds":time.perf_counter()-started})
    summaries=[]
    for arm in ARMS:
        frame=pd.DataFrame(daily[arm]); frame.to_csv(root/f"daily_{arm}.csv",index=False)
        env=inventory[arm]
        sold=float(frame.sales.sum()); expired=float(frame.expiry_units.sum()); demand=float(frame.demand.sum())
        pipeline=sum(p["quantity"] for p in env.pending); closing=float(env.stock().sum())
        residual=env.initial_units+float(frame.purchase_spend.sum())-sold-expired-closing-pipeline
        assert abs(residual)<1e-5, (case,arm,residual)
        summary={"dataset":dataset,"scenario":scenario,"seed":seed,"origin":origin,"arm":arm,"days":7,
            "demand":demand,"sales":sold,"fill_rate":sold/demand if demand else 1.0,
            "operating_cost":float(frame.operating_cost.sum()),
            "cost_per_demand":float(frame.operating_cost.sum()/demand) if demand else 0.0,
            "holding_cost":float(frame.holding_cost.sum()),"shortage_cost":float(frame.shortage_cost.sum()),
            "expiry_cost":float(frame.expiry_cost.sum()),"expiry_units":expired,
            "expiry_share":expired/(env.initial_units+env.total_receipts) if env.initial_units+env.total_receipts else 0.0,
            "purchase_spend":float(frame.purchase_spend.sum()),"initial_stock":env.initial_units,
            "received_units":env.total_receipts,"closing_stock":closing,"closing_pipeline":pipeline,
            "inventory_balance_residual":residual,"mean_inventory":float(frame.stock.mean()),
            "held_days":int(frame.held.sum()),"orders":float(frame.orders.sum()),
            "actual_violations":int(frame.actual_violations.sum()),"source_exact_days":int(frame.source_exact.sum()),
            "source_correct_slots":int(frame.source_correct_slots.sum()),"priority_correct_days":int(frame.priority_correct.sum()),
            "critic_false_approvals":int(frame.critic_false_approval.sum()),"critic_false_holds":int(frame.critic_false_hold.sum()),
            "model_calls":int(frame.model_calls.sum()),"schema_failures":int(frame.schema_failures.sum()),
            "input_tokens":int(frame.input_tokens.sum()),"output_tokens":int(frame.output_tokens.sum()),
            "total_agent_seconds":float(frame.agent_seconds.sum()),"path":str(root.relative_to(OUT))}
        summaries.append(summary)
    dump(root/"summary.json",summaries)
    audit("matched_case_complete",{"case":case,"seconds":time.perf_counter()-started,"runs":3,
        "fresh_calls":sum(r["model_calls"] for r in summaries)})
    return summaries


def execute():
    p=verify(); datasets={(name,origin):load(name,origin) for name in ("M5","RetailNet") for origin in p["datasets"][name]["origins"]}
    cutoff=datetime.fromisoformat(p["experiment_cutoff_utc"])
    summaries=[];started=time.perf_counter();finished_seeds=[]
    if (OUT/"summary.csv").exists(): raise FileExistsError("Fresh execution refuses prior summary")
    audit("evaluation_started",{"protocol_sha256":sha(OUT/"protocol.json")})
    for seed in p["simulation_seeds"]:
        if datetime.now(timezone.utc)>=cutoff: break
        balanced=True
        for scenario in SCENARIOS:
            for dataset,origin in datasets:
                if datetime.now(timezone.utc)>=cutoff:
                    balanced=False;break
                if shutil.disk_usage(ROOT).free < 2*1024**3: raise RuntimeError("Disk reserve below 2 GiB")
                print(json.dumps({"phase":"case_started","dataset":dataset,"origin":origin,"scenario":scenario,"seed":seed,"runs_complete":len(summaries)}),flush=True)
                summaries.extend(run_case(datasets[(dataset,origin)],scenario,seed))
                pd.DataFrame(summaries).to_csv(OUT/"summary.csv",index=False)
                print(json.dumps({"phase":"case_complete","runs_complete":len(summaries),"fresh_calls":sum(s['model_calls'] for s in summaries),"elapsed_seconds":time.perf_counter()-started}),flush=True)
            if not balanced:break
        if balanced: finished_seeds.append(seed)
        else: break
    complete=len(summaries)==p["expected_runs"]
    receipt={"status":"COMPLETE" if complete else "PARTIAL_CUTOFF","completed_at_utc":now(),
        "runs":len(summaries),"portfolio_days":sum(r["days"] for r in summaries),
        "fresh_primary_model_calls":sum(r["model_calls"] for r in summaries),
        "balanced_seeds_complete":finished_seeds,"runtime_seconds":time.perf_counter()-started,
        "expected_runs":p["expected_runs"],"protocol_sha256":sha(OUT/"protocol.json")}
    dump(OUT/"execution_receipt.json",receipt);dump(OUT/"progress.json",receipt);audit("evaluation_finished",receipt)
    print(json.dumps(receipt),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("phase",choices=["develop","freeze","execute"])
    args=parser.parse_args()
    try: {"develop":develop,"freeze":freeze,"execute":execute}[args.phase]()
    except BaseException as exc:
        audit("phase_failed",{"phase":args.phase,"error_type":type(exc).__name__,"message":str(exc)})
        raise
