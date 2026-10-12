# 7. Conclusion and future research

## 7.1 Answering the research questions

This dissertation examined a local language-model workflow for retail replenishment using thirty selected M5 series and thirty selected RetailNet series. Three roles read supplier information, coordinated an approved planning tool and reviewed the release checks. The completed study covered two weekly episodes per dataset, three business situations and thirty simulation seeds. Its purpose was to assess the whole workflow and distinguish its performance from the contribution of the language-model layer.

The first research question concerned the complete package. Relative to conventional ordering, the agent-and-tool workflow improved simulated fulfilment by 25.28 percentage points in M5 and 0.78 points in RetailNet. The paired inventory operating-cost reductions were 70.34% and 4.52%, respectively. The improvement was therefore substantial in the selected M5 world and modest in the selected fresh-retail world. These are comparative simulation findings, rather than observed changes in retailer profit or customer service.

The second question concerned the model's additional contribution. The same structured-data planner performed almost identically in M5 and slightly better in RetailNet. Most of the inventory-performance gain over conventional ordering belongs to the numerical planning capability. The third question concerned role reliability. Supplier reading was completely accurate in the controlled messages, while business-priority selection was less reliable, particularly for RetailNet promotion. The model's demonstrated interpretation strength therefore coexisted with a limitation in applying a declared policy.

## 7.2 The practical conclusion

A small local language model can be a useful replenishment partner when its responsibility is clear. In this study, it successfully converted the tested supplier information into usable rules and participated in a complete guarded process. The evidence supports that bounded language role. It does not establish that the model independently predicts demand or calculates better quantities than a capable numerical planner.

For managers, the recommended starting point is a reliable planner with clear information definitions and supplier limits. Language assistance can then be evaluated where text interpretation creates additional work. Firm policy mappings should remain explicit, and actual field variation should be tested before routine release is expanded. The commercial case should include review effort and the cost of producing structured information, since those possible benefits and burdens were not measured here.

The CPU-only implementation shows that this assessment was feasible with Qwen2.5 1.5B and a modest cloud computer. The model was pretrained and used for inference; LightGBM was fitted to the retail histories. This gives the study a practical local-computing context without implying that the same latency, reliability or economics will hold at every production scale.

## 7.3 A focused next research step

The first priority for future work is an operational comparison of supplier-information preparation. Real messages, staff review time and exception outcomes could show whether the accurate reading role reduces work compared with the current structured process. The same numerical planner should be retained in that comparison so that any additional language-model value can be attributed clearly.

A second priority is understanding promotion-policy selection. The current role made inconsistent choices despite accurate supplier fields. A separately registered study could compare clearer event interpretation, direct policy mappings and alternative local model configurations. A third is extending the operating horizon and the panel, including more varied product lives and realistic commercial costs. That would address stock carry-over and transfer questions that the two weekly simulations cannot resolve.

The overall conclusion is therefore positive and specific. The study demonstrates a working local agent-assisted replenishment process and reliable supplier reading in its controlled setting. Its strongest inventory gains came from the numerical planner. Future development should preserve that strength and test language-model assistance where its interpretation capability can add a separately measured business benefit.
