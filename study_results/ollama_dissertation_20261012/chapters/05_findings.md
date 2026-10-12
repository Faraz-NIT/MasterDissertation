# 5. Findings and interpretation

## 5.1 The main result in one view

The complete registered study finished all 1,080 runs and 7,560 fresh model calls. The central result is straightforward: the agent-and-tool workflow improved on conventional ordering in both datasets, with a much larger improvement in M5. The same numerical planner operating without the language-model roles performed almost identically in M5 and slightly better in RetailNet. The results therefore support the complete workflow while locating most of its inventory-performance gain in the shared planning capability.

The summary table gives the overall policy means. The three business situations receive equal weight, with the two weekly episodes aggregated within each simulation seed. The dataset-specific graphs then show routine trading, supplier disruption and promotion separately. Costs are simulated inventory operating-cost indices, not retailer profits or measured financial savings.

[[TABLE:headline_results]]

## 5.2 M5: a substantial improvement over conventional ordering

In M5, conventional ordering fulfilled 65.05% of the declared demand, compared with 90.33% for the agent-assisted workflow. The improvement was 25.28 percentage points. The workflow's operating-cost index was 70.34% lower in the paired comparison. Both results favour the complete design under the study's assumptions. The figures show that the advantage was present in routine trading, supplier disruption and promotion, rather than confined to one favourable situation.

[[FIGURE:m5_fill]]

[[FIGURE:m5_cost]]

The largest service gap appeared under supplier disruption. Conventional fulfilment was 55.76%, while the agent workflow fulfilled 88.51%. Changed delivery and ordering rules made the simple allocation approach particularly difficult in this simulated portfolio. The constrained planner could apply the same current rules while projecting usable stock and allocating the permitted quantities differently. The result is useful evidence for the package's planning design, although it should not be presented as proof that every conventional retail ordering system would perform this poorly.

The structured-data planner fulfilled 90.34% overall, compared with 90.33% for the agents. Its outcomes matched the agents exactly in routine trading and supplier disruption. The small overall difference came from promotion decisions. The paired uncertainty analysis did not establish an improvement from adding the language-model roles. For M5, the positive business message is that the local agent workflow could participate in a high-performing planning process; the performance gain over conventional ordering also belongs to that process's numerical tool.

## 5.3 RetailNet: a smaller gain with a fresh-stock trade-off

RetailNet conventional ordering fulfilled 83.53% of simulated demand. The agent workflow fulfilled 84.31%, an improvement of 0.78 percentage points. Its paired operating-cost index was 4.52% lower. These gains were much smaller than in M5, and the graphs make that difference visible. The conventional reference was already closer to the stronger planning approach in this selected fresh-retail world, leaving less scope for the complete package to improve its service measure.

[[FIGURE:retailnet_fill]]

[[FIGURE:retailnet_cost]]

RetailNet expiry requires separate attention. The agent workflow's average expired share was 6.95% of opening stock plus receipts. It reduced expiry relative to conventional ordering in routine trading and promotion, while increasing it slightly under supplier disruption. This mixed result is consistent with a practical availability–waste trade-off. The improvement in service and the primary cost index does not mean that every scenario also achieved less expiry. All expiry quantities refer to the hypothetical three-day stock process.

[[FIGURE:retailnet_expiry]]

The structured-data planner fulfilled 84.52% overall and had a lower operating-cost index than the agents. The agent layer reduced service by 0.20 percentage points and increased paired operating cost by 1.01% relative to this stronger reference. The differences were concentrated in promotion handling. RetailNet therefore provides positive evidence for an improvement over the conventional reference, alongside evidence that this small language model did not improve the same planner's numerical performance.

## 5.4 The roles performed differently

The supplier reader correctly extracted all thirteen numerical fields on every primary decision in both datasets. The three controlled message styles all had complete extraction accuracy. This is the clearest demonstrated language-model strength: a small local model successfully converted the tested prose, memos and tables into current supplier information that the planning tool could use. The result concerns the controlled corpus, rather than arbitrary supplier communications.

Priority selection was less consistent. The coordinator selected the expected business priority on 98.97% of M5 decisions and 87.46% of RetailNet decisions. Active promotion was the most difficult condition. The priority-selection graph shows the difference between the overall score and the score on active-promotion days, making the weakness visible rather than allowing routine successes to conceal it. Correctly reading supplier numbers did not guarantee correct interpretation of the trading priority.

[[FIGURE:priority_accuracy]]

The agent workflow held no primary decisions, and there were no committed-action constraint violations across the three policies. These observations concern the guarded process: numerical tools and the execution gate imposed the limits. Mean agent-decision time was 3.68 seconds for M5 and 3.90 seconds for RetailNet on the CPU computer. The additional latency was measured; staff time savings, production cost and commercial return were not.

## 5.5 What the comparison establishes

The first research question has a positive answer within the declared simulation: the complete local workflow improved service and the operating-cost measure relative to conventional ordering. The effect was large in M5 and modest in RetailNet. The second question has a more limited answer: adding the language-model roles did not improve the shared planner, and the RetailNet promotion choices slightly weakened its outcome. The third identifies a clear distinction between successful supplier reading and less consistent business-priority selection.

