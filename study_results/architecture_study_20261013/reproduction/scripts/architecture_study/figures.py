"""Make dataset-labelled chapter figures from the audited architecture comparison."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'study_results/architecture_study_20261013'
FIXED, SELECTIVE, REFERENCE = '#778696', '#287961', '#B3BBC4'


def create():
    summary = json.loads((OUT / 'analysis/analysis_summary.json').read_text())
    assert json.loads((OUT / 'analysis/audit_receipt.json').read_text())['status'] == 'VERIFIED'
    figures = OUT / 'figures'
    figures.mkdir(exist_ok=True)
    register = []
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.facecolor': 'white', 'axes.facecolor': 'white'})
    def save(fig, name, title, scope, caption):
        fig.tight_layout()
        path = figures / (name + '.png')
        fig.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        register.append({'key': name, 'path': str(path.relative_to(OUT)), 'title': title, 'scope': scope, 'caption': caption})
    diagnostics = {(r['dataset'], r['arm']): r for r in summary['diagnostics']}
    effects = {(r['dataset'], r['comparison'], r['metric']): r for r in summary['paired_effects'] if r['scenario'] == 'overall'}
    overall = pd.read_csv(OUT / 'analysis/overall_seed_results.csv')
    days = pd.read_csv(OUT / 'analysis/daily_results.csv')

    dot = '''digraph architecture {
      graph [rankdir=TB, bgcolor="white", pad="0.2", nodesep="0.28", ranksep="0.35"];
      node [shape=box, style="rounded,filled", fillcolor="#F6F8FA", color="#ABB8C4", fontname="Arial", fontsize=12, margin="0.14,0.10"];
      edge [color="#718191", fontname="Arial", fontsize=10];
      intake [label="Supplier intake"];
      parser [label="Declared table\nDeterministic parser"];
      reader [label="Supplier prose\nLLM extraction", fillcolor="#EAF4EE"];
      source [label="Verify current source"];
      policy [label="Apply declared business policy\nDeterministic priority router"];
      planner [label="Shared numerical planner"];
      check [label="Validate proposed action"];
      release [label="Release valid order", fillcolor="#EAF4EE"];
      review [label="Exception review (LLM)\nHold and request review", fillcolor="#FFF5E8"];
      intake -> parser [label="recognised format"];
      intake -> reader [label="prose"];
      parser -> source; reader -> source; source -> policy;
      policy -> planner; planner -> check;
      check -> release [label="all conditions pass"];
      check -> review [label="failed / unknown"];
      parser -> review [label="malformed",style=dashed];
      {rank=same; parser; reader;}
      {rank=same; release; review;}
    }'''
    (figures / 'selective_architecture.dot').write_text(dot)
    for extension in ['png', 'svg']:
        subprocess.run(['dot', '-T'+extension, str(figures / 'selective_architecture.dot'), '-o', str(figures / ('selective_architecture.'+extension))], check=True)
    register.append({'key': 'selective_architecture', 'path': 'figures/selective_architecture.png',
                     'title': 'Selective delegation in the LangGraph workflow', 'scope': 'Architecture',
                     'caption': 'A reader-oriented diagram of the selective path. Failed conditions cannot release an order; review requests are recorded, and no human resolution is simulated. The full executable graph is exported separately as architecture_graph.mmd.'})

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    x = np.arange(2)
    for i, (arm, label, color) in enumerate([('fixed_agents','Fixed workflow',FIXED),('selective_agents','Selective workflow',SELECTIVE)]):
        values = [diagnostics[(ds,arm)]['fresh_model_calls']/diagnostics[(ds,arm)]['portfolio_days'] for ds in ['M5','RetailNet']]
        bars = ax.bar(x+(i-.5)*.32, values, .32, label=label, color=color)
        ax.bar_label(bars, fmt='%.2f', padding=3)
    ax.set_xticks(x, ['M5', 'RetailNet'])
    ax.set_ylabel('Native model calls per decision')
    ax.set_ylim(0, 3.55)
    ax.set_title('M5 and RetailNet — model calls required')
    ax.legend(frameon=False)
    ax.grid(axis='y', alpha=.15)
    save(fig, 'model_calls', 'Model calls per replenishment decision', 'M5 + RetailNet',
         'Calls include every attempted native model call. The same model and generation settings were used. Structured-table parsing is a declared architectural route, not a reused model response.')

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    for i, (arm, label, color) in enumerate([('fixed_agents','Fixed workflow',FIXED),('selective_agents','Selective workflow',SELECTIVE)]):
        values = [diagnostics[(ds,arm)]['mean_decision_seconds'] for ds in ['M5','RetailNet']]
        bars = ax.bar(x+(i-.5)*.32, values, .32, label=label, color=color)
        ax.bar_label(bars, fmt='%.2f s', padding=3)
    ax.set_xticks(x, ['M5', 'RetailNet'])
    ax.set_ylabel('Mean decision time (seconds)')
    ax.set_ylim(0, max(diagnostics[(ds,'fixed_agents')]['mean_decision_seconds'] for ds in ['M5','RetailNet'])*1.3)
    ax.set_title('M5 and RetailNet — decision time on the same CPU instance')
    ax.legend(frameon=False)
    ax.grid(axis='y', alpha=.15)
    save(fig, 'decision_time', 'Mean time per replenishment decision', 'M5 + RetailNet',
         'Measured whole-decision blocks, including graph orchestration and the numerical tool. Fixed/selective order was counterbalanced. This describes the experimental instance, not employee time or production cost.')

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), sharey=True)
    for ax, ds in zip(axes, ['M5','RetailNet']):
        for i, (arm, label, color) in enumerate([('fixed_agents','Fixed',FIXED),('selective_agents','Selective',SELECTIVE)]):
            values = [100*diagnostics[(ds,arm)][k] for k in ['priority_accuracy','active_promotion_accuracy']]
            bars = ax.bar(np.arange(2)+(i-.5)*.32, values, .32, label=label, color=color)
            ax.bar_label(bars, fmt='%.1f', padding=2, fontsize=9)
        ax.set_xticks(np.arange(2), ['All decisions','Active promotion'])
        ax.set_ylim(0, 115)
        ax.set_title(ds)
        ax.grid(axis='y', alpha=.15)
    axes[0].set_ylabel('Expected priority selected (%)')
    axes[1].legend(frameon=False, loc='lower right')
    fig.suptitle('M5 and RetailNet — reliability of business-priority selection')
    save(fig, 'priority_accuracy', 'Correct application of the declared business priority', 'M5 + RetailNet',
         'Accuracy is scored against the policy available before ordering. Active promotion covers days 2–6. Explicit policy routing does not demonstrate that the model itself improved its reasoning.')

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8))
    for ax, metric, sign, label in [(axes[0],'fill_rate',1,'Fill-rate change (percentage points)'),
                                   (axes[1],'cost_per_demand',-1,'Operating-cost reduction (%)')]:
        values, lows, highs = [], [], []
        for ds in ['M5','RetailNet']:
            e = effects[(ds,'fixed_agents',metric)]
            values.append(sign*e['mean'])
            lows.append(sign*e['ci_low'] if sign == 1 else -e['ci_high'])
            highs.append(sign*e['ci_high'] if sign == 1 else -e['ci_low'])
        ax.errorbar(x, values, yerr=[np.array(values)-lows, np.array(highs)-values], fmt='o', color=SELECTIVE, capsize=5, markersize=7)
        ax.axhline(0, color='#778696', linewidth=.8)
        ax.set_xticks(x, ['M5','RetailNet'])
        ax.set_ylabel(label)
        ax.grid(axis='y', alpha=.15)
    fig.suptitle('Change from the fixed workflow — M5 and RetailNet')
    save(fig, 'inventory_effects', 'Inventory-performance change relative to the fixed workflow', 'M5 + RetailNet',
         'Points show paired simulation-seed means; intervals are 95% bootstrap intervals for 30 simulated seeds. Positive values favour selective delegation in both panels. Costs are synthetic inventory operating-cost indices, not realised savings.')

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    scenarios = ['routine','supplier_disruption','promotion']
    for i, (arm, label, color) in enumerate([('fixed_agents','Fixed workflow',FIXED),('selective_agents','Selective workflow',SELECTIVE)]):
        values = [100*next(m['expiry_share']['mean'] for m in summary['policy_means'] if m['dataset']=='RetailNet' and m['scenario']==s and m['arm']==arm) for s in scenarios]
        bars = ax.bar(np.arange(3)+(i-.5)*.32, values, .32, label=label, color=color)
        ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=9)
    ax.set_xticks(np.arange(3), ['Routine','Supplier disruption','Promotion'])
    ax.set_ylabel('Expired stock / opening stock and receipts (%)')
    ax.set_title('RetailNet — the availability and waste trade-off')
    ax.legend(frameon=False)
    ax.grid(axis='y', alpha=.15)
    save(fig, 'retailnet_expiry', 'Expiry outcomes by RetailNet operating situation', 'RetailNet',
         'Hypothetical three-day FIFO stock process. A service or cost improvement does not necessarily imply less waste. M5 has no expiry within the evaluated horizon.')

    (OUT / 'figure_register.json').write_text(json.dumps({'figures': register,
        'source_analysis': 'analysis/analysis_summary.json'}, indent=2)+'\n')
    print(json.dumps({'figures': len(register)}))


if __name__ == '__main__':
    create()
