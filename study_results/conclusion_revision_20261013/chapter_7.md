# 7. Conclusion and future research

## 7.1 The main conclusion

This dissertation asked whether LLM agents can improve retail replenishment and what they contribute beyond an established numerical planner. The study used thirty selected series from M5 and thirty from FreshRetailNet-50K, referred to as RetailNet. It evaluated routine trading, supplier disruption and promotion across two weekly episodes per dataset, with thirty simulation seeds.

The complete agent-supported workflow improved service and simulated operating cost compared with conventional ordering. Its largest benefit appeared in M5. However, adding the LLM roles did not improve the same numerical planner's service or cost performance. The clearest demonstrated contribution of the language model was accurately reading the tested supplier information and making it available to the planning process.

The system ran pretrained Qwen2.5 1.5B through Ollama on a Linux cloud instance with four allocated CPU cores, 32 GiB of memory and no GPU. Qwen was used for inference and was not trained or fine-tuned on either dataset. The separate LightGBM forecaster was fitted to past retail sales.

## 7.2 Answers to the research questions

### RQ1. Does the complete system improve replenishment?

Yes, within the simulated settings. In M5, the workflow increased fill rate from 65.05% to 90.33%, a gain of 25.28 percentage points, and reduced the simulated operating-cost index by 70.34%. In RetailNet, fill rate increased from 83.53% to 84.31%, a gain of 0.78 percentage points, while the cost index fell by 4.52%. The uncertainty intervals favoured the complete workflow for both outcomes in both datasets. These improvements support the system as a package; they do not isolate the LLM's contribution.

### RQ2. What additional value does the LLM contribute?

The study found no additional service or cost benefit over the same planner receiving equivalent structured information without an LLM. In M5, the observed outcomes were nearly identical and the small differences were inconclusive. In RetailNet, the agent workflow had a fill rate 0.20 percentage points lower and a cost index 1.01% higher than the same-planner comparison. Most of the improvement over conventional ordering therefore came from the shared planning capability. The LLM successfully supplied information to that capability, but possible savings in staff time were not measured.

### RQ3. Which agent tasks are performed most reliably?

Supplier fact extraction was the strongest task. It was completely accurate on the controlled messages in both datasets. Business-priority selection was less reliable: accuracy was 98.97% in M5 and 87.46% in RetailNet. Promotion handling was the main weakness, with only 47.33% of active RetailNet promotion decisions selecting the expected priority. These results support a clear distinction between reading explicit facts and consistently applying a business instruction. There were no committed-action constraint violations, but the numerical tools and release checks enforced those limits; this outcome alone does not establish the quality of every agent decision.

### RQ4. How does performance differ between M5 and RetailNet?

The observed improvement over conventional ordering was much larger in M5 than in RetailNet. The conventional RetailNet policy already achieved a higher fill rate, leaving less room for improvement. Its fresh-stock setting also introduced an availability–waste trade-off. These observations indicate sensitivity to the retail setting, but the original analysis did not include a formal test comparing the effects between datasets. The answer is therefore descriptive and exploratory. The difference cannot be attributed solely to perishability because the datasets and their modelling assumptions differ in other respects.

## 7.3 Assessment of the hypotheses

The hypothesis assessments below follow the framework stated in Chapter 2. They concern the evaluated simulation and controlled message tasks. The framework was not presented as a preregistered confirmatory protocol.

| Hypothesis | Assessment | What the evidence shows |
| --- | --- | --- |
| H1a: Higher fill rate than conventional ordering | Supported in both datasets | The complete workflow served a larger share of simulated demand. |
| H1b: Lower simulated cost than conventional ordering | Supported in both datasets | The complete workflow reduced the primary operating-cost index. |
| H2a: Higher fill rate than the same planner without an LLM | Not supported | The M5 difference was inconclusive; RetailNet service was lower. |
| H2b: Lower simulated cost than the same planner without an LLM | Not supported | The M5 difference was inconclusive; RetailNet cost was higher. |
| H3: Fact extraction is more reliable than priority selection | Supported for the controlled tasks | Fact extraction accuracy exceeded priority-selection accuracy in both datasets. |
| H4: The benefit differs between M5 and RetailNet | Exploratory; formal support not established | The observed gains differed substantially, but a cross-dataset effect test was not performed. |

H1 supports the value of the complete design. H2 prevents that result from being attributed entirely to the language model. H3 identifies where the agents were most useful, while H4 establishes a question for further testing rather than a confirmed explanation of the dataset difference.

## 7.4 Business implications and study boundaries

For a retailer, the strongest use case suggested by this study is a language layer that prepares information for a reliable planner. A small local model successfully converted the tested supplier messages into usable inputs. That capability could be valuable where employees spend time reading and entering operational updates. A business case would still need to measure those time savings against checking, integration and computing costs. Priority rules should remain explicit, especially where an incorrect interpretation can affect service.

The evidence has clear boundaries. It covers selected product series, two short episodes and controlled supplier messages, rather than a live retail deployment. Fill rate relates to the study's demand definition, not directly observed unmet customer demand. RetailNet's stock-life assumptions were simulated, and expiry did not improve in every scenario. The cost index represents modelled inventory costs; it excludes several costs of implementation and does not measure retailer profit. These boundaries make the findings useful for a targeted pilot rather than sufficient for unrestricted deployment.

## 7.5 Future research

The first priority is a practical pilot using genuine supplier communications. It should compare employee preparation time, extraction errors, review effort and replenishment outcomes while retaining the same numerical planner. This would test whether the language role creates business value even when order performance is similar to a structured-information process.

A second priority is business-priority selection. Future work should test clearer instructions, explicit policy mappings and alternative local model configurations under the same conditions. It should evaluate each task separately so that reliable supplier reading does not conceal inconsistent promotion decisions.

A third priority is a broader and longer evaluation. More products, additional periods, varied shelf lives and realistic commercial costs would help assess stock carry-over, waste and transfer to other retail settings. A future protocol should state the hypotheses and assessment criteria before analysis and include an explicit comparison of the effects across M5 and RetailNet. These steps would strengthen the evidence for H4 and help establish which operating conditions make agent support worthwhile.

## 7.6 Closing conclusion

The study demonstrates a workable role for a small local LLM in replenishment: interpreting the tested supplier information within a disciplined planning process. The complete workflow improved on conventional ordering, while its numerical planner accounted for most of the inventory-performance gain. Future development should build on the demonstrated reading capability and measure the value it creates in everyday retail work.
