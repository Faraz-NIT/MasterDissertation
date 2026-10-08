"""Redraw accessible, dataset-labelled figures from completed study artifacts."""
from __future__ import annotations
import hashlib,json,os,textwrap
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/business-dissertation-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'study_results/business_dissertation'
FRESH=ROOT/'study_results/freshretailnet'
BLUE='#24548A';GREEN='#27775D';ORANGE='#BD7026';GREY='#737C86';INK='#22333B'
SCENARIOS=['normal','derived_field_collapse','feed_gap','capacity_cut']
LABELS=['Normal','Inventory-field\nfault','Stale\ninformation','Capacity\nreduction']
POLICIES=['Seasonal\nrule','ML reorder\nrule','Constrained\noptimizer','Optimizer +\napproval']
plt.rcParams.update({'font.family':'Liberation Serif','font.size':15,'axes.labelsize':16,
 'axes.titlesize':17,'xtick.labelsize':14,'ytick.labelsize':14,'legend.fontsize':13,
 'axes.spines.top':False,'axes.spines.right':False,'axes.labelcolor':INK,
 'text.color':INK,'axes.titlecolor':INK,'figure.facecolor':'white','savefig.facecolor':'white'})
inputs={};figures=[];numbers={}
def sha(p):
 with Path(p).open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
def csv(p):
 p=ROOT/p;inputs[str(p.relative_to(ROOT))]={'sha256':sha(p),'bytes':p.stat().st_size};return pd.read_csv(p)
def js(p):
 p=ROOT/p;inputs[str(p.relative_to(ROOT))]={'sha256':sha(p),'bytes':p.stat().st_size};return json.loads(p.read_text())
def save(key,dataset,title,caption,fig,values=None):
 heading=textwrap.fill(f'{dataset} | {title}',width=74)
 fig.suptitle(heading,fontsize=18,fontweight='bold',y=.995)
 fig.tight_layout(pad=1.0,rect=(0,0,1,.82 if '\n' in heading else .90))
 path=OUT/'figures'/f'{key}.png';fig.savefig(path,dpi=180,bbox_inches='tight');plt.close(fig)
 figures.append({'key':key,'dataset':dataset,'title':title,'caption':caption,'path':str(path.relative_to(OUT)),'sha256':sha(path)})
 if values is not None:numbers[key]=values
def two():return plt.subplots(1,2,figsize=(10.4,4.1))
def annotate(ax,fmt='{:.1f}'):
 for rect in ax.patches:
  h=rect.get_height();ax.annotate(fmt.format(h),(rect.get_x()+rect.get_width()/2,h),xytext=(0,-5 if h<0 else 5),textcoords='offset points',ha='center',va='top' if h<0 else 'bottom',fontsize=14)
def boxes(key,title,texts,caption):
 fig,ax=plt.subplots(figsize=(10.4,3.0));ax.axis('off');n=len(texts)
 for i,(heading,body) in enumerate(texts):
  x=i/n+.012;w=1/n-.038
  ax.add_patch(FancyBboxPatch((x,.2),w,.63,boxstyle='round,pad=0.01',transform=ax.transAxes,facecolor='#EAF0F4',edgecolor=BLUE,linewidth=1.2))
  ax.text(x+w/2,.70,heading,ha='center',va='center',transform=ax.transAxes,fontweight='bold',fontsize=16)
  ax.text(x+w/2,.45,body,ha='center',va='center',transform=ax.transAxes,fontsize=14)
  if i<n-1:ax.annotate('',xy=((i+1)/n-.004,.51),xytext=(x+w+.006,.51),xycoords=ax.transAxes,arrowprops={'arrowstyle':'->','color':INK,'lw':1.4})
 save(key,'M5 + RETAILNET',title,caption,fig)

def main():
 (OUT/'figures').mkdir(parents=True,exist_ok=True)
 m=csv('study_results/v2/M5_v2_results.csv')
 mv1=csv('study_results/v1/M5_six_hour_results.csv')
 f=csv('study_results/freshretailnet/FreshRetailNet_exploratory_gate_transfer_all_runs.csv')
 primary=csv('study_results/freshretailnet/FreshRetailNet_agent_all_runs.csv')
 numeric=csv('study_results/freshretailnet/FreshRetailNet_numerical_means.csv')
 paired=csv('study_results/freshretailnet/FreshRetailNet_exploratory_repair_paired_seed_effects.csv')
 transition=csv('study_results/freshretailnet/FreshRetailNet_gate_transition_original_seed_pairs.csv')
 sens=csv('study_results/freshretailnet/FreshRetailNet_sensitivity_means.csv')
 policies=csv('study_results/freshretailnet/FreshRetailNet_policy_sensitivity_all_runs.csv')
 forecast=js('results/freshretailnet/forecast/summary.json')
 train=js('study_results/freshretailnet/receipts/data/train_validation.json')
 evaluation=js('study_results/freshretailnet/receipts/data/eval_validation.json')
 oldreport=js('study_results/v1/M5_six_hour_study_report_data.json')
 assert len(m)==32 and len(mv1)==372 and len(f)==480 and len(primary)==32 and len(policies)==1140
 mg=m.groupby(['arm','scenario'])[['cost','fill_rate']].mean()
 fg=f.groupby(['arm','scenario'])[['cost','fill_rate','held_decisions']].mean()
 boxes('decision_workflow','From information to an approved order',[
  ('Check records','Inventory and\nsource freshness'),('Read rules','LLM or\nrule-based reader'),('Calculate','Forecast and\nplanning tool'),('Approve','Independent checks\nor a recorded hold')],
  'Workflow schematic used to explain both studies. The language model interprets bounded inputs; numerical tools calculate orders and independent checks control execution. This is not an additional experimental result.')
 boxes('evidence_layers','Three kinds of information',[('Observed','Published sales\nand availability'),('Estimated','Forecasts and\nrecovered sales'),('Simulated','Inventory, supply,\nexpiry and costs')],
  'Evidence classification. These categories must be distinguished even when they appear together in a planning record. Natural lost demand is not observed.')
 fig,axs=two()
 for ax,title,values,color in [(axs[0],'M5 panel',[30,3,10],BLUE),(axs[1],'RetailNet panel',[30,26,29],GREEN)]:
  ax.bar(['Series','Products','Stores'],values,color=color);ax.set_title(title);ax.set_ylabel('Selected count');ax.set_ylim(0,36);annotate(ax,'{:.0f}')
 save('panel_profiles','M5 + RETAILNET','The computational panels',
  'Both panels have thirty store–product series. M5 has three selected food products across ten stores; RetailNet has twenty-six products and twenty-nine stores. Full-release validation is separate from panel performance evaluation.',fig,{'m5':[30,3,10],'retailnet':[30,26,29]})
 # Full-release availability values come from the source-validation receipts.
 availability=[]
 for label,receipt in [('Training',train),('Evaluation',evaluation)]:
  availability.append({'partition':label,'hour_pct':100*receipt['operating_hour_stockout_fraction'],'day_pct':100*receipt['daily_any_stockout_fraction']})
 fig,ax=plt.subplots(figsize=(10.4,4.1));x=np.arange(2)
 ax.bar(x-.19,[r['hour_pct'] for r in availability],.36,color=GREEN,label='Operating hours with stockout')
 ax.bar(x+.19,[r['day_pct'] for r in availability],.36,color=ORANGE,label='Days with any stockout hour')
 ax.set_xticks(x,['Training release','Evaluation release']);ax.set_ylabel('Share of observations (%)');ax.set_ylim(0,59);ax.legend(loc='upper right');annotate(ax,'{:.1f}%')
 save('retailnet_availability','RETAILNET','Sales were often availability-constrained',
  'Complete pinned release: training and evaluation files. Hourly and daily percentages use different denominators. Operating hours are 06:00–21:00. These observations identify availability conditions; they do not quantify true lost demand.',fig,availability)
 boxes('study_map','How the experiments answer different questions',[
  ('Numerical controls','Ordering policies\nand approval'),('Matched readers','LLM contribution\nand verified repair'),('Fresh-product tests','Forecast recovery\nand service–waste')],
  'Study map. M5 and RetailNet include numerical and matched-reader work. Separate forecasting and fresh-product calculator analyses use RetailNet and contain no language-model calls.')
 for data,key,dataset,no,yes,note in [(mg,'m5_repair','M5','llm_v2_no_recovery','llm_v2_recovery','Improved M5 pilot; thirty series, fourteen days, two shared seeds. Simulated cost uses the M5 study monetary conventions.'),
  (fg,'retailnet_repair','RETAILNET','llm_no_recovery','llm_recovery','Exploratory calibrated follow-up; thirty series, seven days, thirty seeds. Reused holdout. Cost is an index, not retailer currency.')]:
  before=data.loc[(no,'derived_field_collapse')];after=data.loc[(yes,'derived_field_collapse')];fig,axs=two()
  for ax,vals,ylabel,fmt in [(axs[0],[before.cost,after.cost],'Simulated cost' if dataset=='M5' else 'Simulated cost index','{:.0f}'),(axs[1],[100*before.fill_rate,100*after.fill_rate],'Demand fulfilled (%)','{:.1f}%')]:
   ax.bar(['Without repair','With verified repair'],vals,color=[GREY,BLUE if dataset=='M5' else GREEN]);ax.set_ylabel(ylabel);ax.set_ylim(0,max(vals)*1.23);annotate(ax,fmt)
  save(key,dataset,'Verified repair under an inventory-field fault',note+' The matched rule-based reader achieved the same results.',fig,{'cost_before':before.cost,'cost_after':after.cost,'fill_before':before.fill_rate,'fill_after':after.fill_rate,'cost_change_pct':100*(after.cost/before.cost-1),'fill_change_pp':100*(after.fill_rate-before.fill_rate)})
 fig,axs=two();values=[]
 for status in ['no_recovery','recovery']:
  ll=m[m.arm.eq('llm_v2_'+status)];p=m[m.arm.eq('parser_'+status)];a=ll.merge(p,on=['scenario','seed'],suffixes=('_llm','_parser'),validate='one_to_one');values.extend(a[['cost_llm','cost_parser','fill_rate_llm','fill_rate_parser']].to_dict('records'))
  for ax,col,scale in [(axs[0],'cost',1),(axs[1],'fill_rate',100)]:ax.scatter(a[col+'_parser']*scale,a[col+'_llm']*scale,s=60,color=BLUE if status=='recovery' else GREY,marker='s' if status=='recovery' else 'o',label='With repair' if status=='recovery' else 'Without repair')
 for ax,ylabel in zip(axs,['Simulated cost','Demand fulfilled (%)']):
  low,high=ax.get_xlim();ax.plot([low,high],[low,high],color=ORANGE,ls='--',label='Equal outcomes');ax.set_xlabel('Rule-based reader');ax.set_ylabel('LLM reader');ax.set_title(ylabel);ax.legend(fontsize=12)
 save('m5_reader_parity','M5','Reader comparisons lie on the equality line','Improved pilot: sixteen matched scenario/seed/recovery comparisons. Some points overlap because outcomes are equal. Exact daily actions also matched; equal cost and service are not evidence of incremental LLM superiority.',fig,values)
 methods=['seasonal_naive_raw','lightgbm_raw','lightgbm_gbm_recovered','lightgbm_profile_recovered'];names=['Weekly\nreference','LightGBM\nraw sales','LightGBM\ntree recovery','LightGBM\nprofile recovery']
 fm={r['method']:r for r in forecast['eval_metrics'] if r['target_kind']=='fully_in_stock_daily_sales'}
 fig,ax=plt.subplots(figsize=(10.4,4.1));vals=[fm[k]['wape']*100 for k in methods]
 ax.bar(names,vals,color=[GREY,GREEN,ORANGE,'#83A595']);ax.set_ylabel('Forecast error: WAPE (%)');ax.set_ylim(0,54);annotate(ax,'{:.2f}%')
 save('retailnet_forecast','RETAILNET','Unadjusted-sales LightGBM led the main forecast test','Official evaluation, 114 fully stocked panel-days out of 210. Lower WAPE is better. Models were selected before evaluation unsealing. These are numerical methods, not LLM forecasts.',fig,dict(zip(methods,vals)))
 tr=transition[transition.arm.eq('llm_recovery')].set_index('scenario').loc[SCENARIOS]
 fig,axs=two();x=np.arange(4)
 for ax,before,after,ylabel in [(axs[0],tr.primary_fill*100,tr.calibrated_fill*100,'Demand fulfilled (%)'),(axs[1],tr.primary_held_days/2,tr.calibrated_held_days/2,'Mean held days per seven-day run')]:
  ax.bar(x-.18,before,.34,color=GREY,label='Original cap');ax.bar(x+.18,after,.34,color=GREEN,label='Calibrated cap');ax.set_xticks(x,LABELS);ax.set_ylabel(ylabel);ax.set_ylim(0,max(max(before),max(after))*1.2);ax.legend(fontsize=12)
 save('retailnet_cap_transfer','RETAILNET','Approval policy had to fit the new setting','Matched cap transition at the original two seeds, 13 and 29, for the LLM-with-repair configuration; the reader counterpart is equal. Original cap 1,500, training-selected cap 1,850. Follow-up is exploratory and reuses the holdout.',fig,tr.reset_index().to_dict('records'))
 q=paired[paired.scenario.eq('derived_field_collapse')].sort_values('seed');fig,axs=two()
 for ax,col,ylabel in [(axs[0],'repair_minus_no_repair_cost','Repair minus no-repair cost index'),(axs[1],'repair_minus_no_repair_fill_pp','Repair minus no-repair fill (points)')]:
  colors=[ORANGE if v>0 and 'cost' in col else GREEN for v in q[col]];ax.scatter(q.seed,q[col],c=colors,s=45);ax.axhline(0,color=GREY,lw=1);ax.set_xlabel('Shared simulation seed');ax.set_ylabel(ylabel)
 save('retailnet_seed_variation','RETAILNET','The repair benefit varied across seeds','Exploratory follow-up, inventory-field fault, thirty paired seeds. Cost decreased in 26/30 seeds; orange points show the four adverse cost outcomes. Fill increased in 30/30. Simulation seeds are not independent stores or historical weeks.',fig,q.to_dict('records'))
 b3=numeric[numeric.policy.eq('B3')&numeric.scenario.eq('normal')].iloc[0];cal=fg.loc[('llm_recovery','normal')];fig,axs=two()
 for ax,vals,ylabel,fmt in [(axs[0],[b3.cost,cal.cost],'Simulated cost index','{:.0f}'),(axs[1],[b3.fill_rate*100,cal.fill_rate*100],'Demand fulfilled (%)','{:.2f}%')]:
  ax.bar(['Constrained\noptimizer','Calibrated approval\nworkflow'],vals,color=[GREY,GREEN]);ax.set_ylabel(ylabel);ax.set_ylim(0,max(vals)*1.24);annotate(ax,fmt)
 save('retailnet_conventional_comparison','RETAILNET','Lower cost came with lower service','Normal scenario, the same thirty seeds and seven-day horizon. Conventional optimizer: primary numerical study. Approval workflow: exploratory calibrated follow-up. Both had zero actual committed-rule violations. No overall-winner claim is supported.',fig,{'conventional_cost':b3.cost,'approval_cost':cal.cost,'conventional_fill':b3.fill_rate,'approval_fill':cal.fill_rate})
 ss=sens[sens.calculator.eq('age_aware')&sens.demand_multiplier.eq(1.25)];fig,axs=two()
 for history,color,label in [('raw',GREY,'Raw history'),('selected_recovery',GREEN,'Recovered history')]:
  rows=ss[ss.history.eq(history)].sort_values('shelf_life_days')
  for ax,metric,ylabel in [(axs[0],'fill_rate','Demand fulfilled (%)'),(axs[1],'waste_fraction','Available stock expired (%)')]:
   ax.plot(rows.shelf_life_days,rows[metric]*100,'o-',color=color,label=label,lw=2);ax.set_xticks([1,3,7]);ax.set_xlabel('Assumed shelf life (days)');ax.set_ylabel(ylabel);ax.legend(fontsize=12)
 save('retailnet_perishability','RETAILNET','Fresh-product service and expiry must be read together','Separate age-aware calculator analysis, thirty seeds per cell, assumed demand multiplier 1.25. Waste denominator is opening stock plus receipts. Shelf lives are hypothetical. No LLM calls; units and supply differ from the main optimizer study.',fig,ss.to_dict('records'))
 f4=policies[policies.experiment.eq('F4')].groupby('gate')[['fill_rate','total_cost_index','held_series_days']].mean();assert len(f4)==2
 good=f4.loc['censoring_aware'];bad=f4.loc['naive_stockout_hold'];fig,axs=two();fig.set_size_inches(10.4,3.6)
 for ax,vals,ylabel,fmt in [(axs[0],[good.fill_rate*100,bad.fill_rate*100],'Demand fulfilled (%)','{:.2f}%'),(axs[1],[good.total_cost_index,bad.total_cost_index],'Separate calculator cost index','{:.1f}')]:
  ax.bar(['Availability-aware','Hold on stockout'],vals,color=[GREEN,ORANGE]);ax.set_ylabel(ylabel);ax.set_ylim(0,max(vals)*1.24);annotate(ax,fmt)
 save('retailnet_stockout_rule','RETAILNET','A valid stockout flag should inform the decision','Sixty separate calculator runs, thirty shared seeds, three-day life and assumed demand multiplier 1.25. Hold-on-stockout is a deliberately defective ablation, not a strong competitor. Neither configuration uses an LLM.',fig,f4.reset_index().to_dict('records'))
 effects=numbers['m5_repair'],numbers['retailnet_repair'];fig,axs=two();fig.set_size_inches(10.4,3.6);labels=['M5\nImproved pilot\n2 seeds / 14 days','RetailNet\nOriginal cap\n2 seeds / 7 days','RetailNet\nCalibrated cap\n30 seeds / 7 days']
 for ax,vals,ylabel in [(axs[0],[effects[0]['cost_change_pct'],0,effects[1]['cost_change_pct']],'Mean cost change from repair (%)'),(axs[1],[effects[0]['fill_change_pp'],0,effects[1]['fill_change_pp']],'Fill change from repair (points)')]:
  ax.bar(labels,vals,color=[BLUE,GREY,GREEN]);ax.axhline(0,color=GREY,lw=1);ax.set_ylabel(ylabel);ax.margins(y=.23);annotate(ax,'{:.2f}')
 save('cross_dataset_repair','M5 + RETAILNET','Within-setting repair effects','Descriptive comparison, inventory-field-fault scenario. M5: improved pilot. RetailNet original: fixed-cap primary study. RetailNet calibrated: exploratory reused-holdout follow-up. Economic scales and horizons differ; the reader achieves the same effects as the LLM.',fig,{'m5':effects[0],'retailnet_primary':{'cost_change_pct':0,'fill_change_pp':0},'retailnet_exploratory':effects[1]})
 fig,ax=plt.subplots(figsize=(10.4,4.1));labels=['M5 improved\n20 requests','RetailNet primary\n12 requests','RetailNet exploratory\n180 requests'];ok=[10,6,90];bad=[10,6,90];x=np.arange(3)
 ax.bar(x,ok,color=GREEN,label='Appropriate recovery choice');ax.bar(x,bad,bottom=ok,color=ORANGE,label='Stale-source choice refused');ax.set_xticks(x,labels);ax.set_ylabel('Actual selector responses');ax.set_ylim(0,240);ax.legend();
 for i,(a,b) in enumerate(zip(ok,bad)):ax.text(i,a/2,str(a),ha='center',color='white',fontsize=15);ax.text(i,a+b/2,str(b),ha='center',color='white',fontsize=15)
 save('recovery_choices','M5 + RETAILNET','Tools contained inappropriate recovery requests','Request-level observations, shown separately by study. All stale-source repair requests were refused. Cached reader imports are not additional model judgements. Correct formatting does not establish correct tool choice.',fig,{'appropriate':ok,'stale_refused':bad})
 boxes('adoption_path','A proposed route to operational testing',[('Baseline','Measure the current\nprocess and records'),('Shadow pilot','Compare proposals\nwithout execution'),('Limited authority','Defined products,\nlimits and review'),('Broader pilot','Measure service,\nwaste and workload')],
  'Managerial recommendation derived from the findings. This operational pilot was not conducted as part of the dissertation and does not represent an observed deployment result.')
 # Appendix figures retain useful detail without lengthening the main results narrative.
 fb=pd.DataFrame(oldreport['forecast_backtests']);fb=fb[fb.evaluation_role.eq('pre-main-study holdout')];a=fb.groupby('model').wrmsse.mean().sort_values();fig,ax=plt.subplots(figsize=(10.4,4.1));ax.bar([x.replace('_',' ').title() for x in a.index],a.values,color=BLUE);ax.set_ylabel('Mean scaled forecast error (WRMSSE)');ax.set_ylim(0,max(a.values)*1.2);annotate(ax,'{:.2f}')
 save('m5_forecast_context','M5','Historical forecasting context','Retained reduced-panel pre-main-study backtests; thirty bottom series and 112 aggregate nodes. The two origins overlap and are descriptive. Lower is better. This is not a full M5 competition ranking or an LLM forecasting result.',fig,a.to_dict())
 recover=forecast['selection']['recovery']['candidates'];fig,ax=plt.subplots(figsize=(10.4,4.1));ax.bar(['Zero filling','Hourly profile','Tree recovery'],[next(r['mae'] for r in recover if r['method']==k) for k in ['raw_zero','profile','gbm']],color=[GREY,ORANGE,GREEN]);ax.set_ylabel('Hidden-hour absolute error (normalized sales)');ax.set_ylim(0,.073);annotate(ax,'{:.4f}')
 save('retailnet_mask_recovery','RETAILNET','Artificial-mask hourly reconstruction','Training-validation test on originally fully stocked days; 6,930 hidden target hours and 2-, 4-, 8-hour masks. Lower MAE is better. This does not identify naturally unserved demand and contains no LLM calls.',fig,recover)
 mn=mv1[mv1.comparison_group.eq('numerical_7_days')].groupby(['policy','scenario'])[['cost','fill_rate','hard_violations']].agg({'cost':'mean','fill_rate':'mean','hard_violations':'sum'}).reset_index()
 for frame,key,dataset,note in [(mn,'m5_numerical_overview','M5','Original numerical study; thirty seeds per policy/scenario and seven days. Cost follows M5 model conventions.'),(numeric,'retailnet_numerical_overview','RETAILNET','Primary numerical study; thirty seeds per policy/scenario and seven days. Costs are indices. The approval policy retains the original cap.')]:
  normal=frame[frame.scenario.eq('normal')].set_index('policy').loc[['B1','B2','B3','B4']];fig,axs=two()
  axs[0].bar(POLICIES,normal.fill_rate*100,color=BLUE if dataset=='M5' else GREEN);axs[0].set_ylabel('Normal-scenario demand fulfilled (%)');axs[0].set_ylim(0,112)
  v=frame.groupby('policy').hard_violations.sum().reindex(['B1','B2','B3','B4']);axs[1].bar(POLICIES,v.values,color=ORANGE);axs[1].set_ylabel('Actual violated checks across scenarios');axs[1].set_ylim(0,max(v.max()*1.25,1));annotate(axs[1],'{:.0f}')
  save(key,dataset,'Numerical controls: service and active-rule compliance',note+' Violated checks are not reference-only action deviations and can exceed the number of affected days. These are conventional policies, not the matched LLM-versus-reader experiment.',fig,{'normal':normal.reset_index().to_dict('records'),'violated_checks':v.to_dict()})
 age=sens[sens.calculator.eq('age_aware')&sens.history.eq('raw')];fig,ax=plt.subplots(figsize=(10.4,4.1))
 for life,color in [(1,ORANGE),(3,GREEN),(7,BLUE)]:
  a=age[age.shelf_life_days.eq(life)].sort_values('demand_multiplier');ax.plot(a.demand_multiplier,a.cost,'o-',color=color,label=f'{life}-day assumed life',lw=2)
 ax.set_xlabel('Assumed demand multiplier');ax.set_ylabel('Separate calculator cost index');ax.set_xticks([1,1.25,1.5]);ax.legend()
 save('retailnet_expiry_sensitivity','RETAILNET','Cost depends on demand and shelf-life assumptions','Separate age-aware calculator with raw history and thirty seeds per cell. Neither assumed demand nor shelf life is observed natural ground truth. No LLM calls; this cost index is not pooled with the main optimizer.',fig,age.to_dict('records'))
 assert len(figures)==22
 (OUT/'figure_register.json').write_text(json.dumps({'figures':figures,'inputs':inputs,'plotted_values':numbers},indent=2)+'\n')
 print(json.dumps({'status':'BUILT','figures':len(figures),'inputs':len(inputs)}))

if __name__=='__main__':main()
