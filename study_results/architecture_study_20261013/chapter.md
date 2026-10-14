# A selective agent architecture for retail replenishment

## 1. Purpose and architectural contribution

The earlier study showed that a small language model could read supplier information reliably, while its business-priority decisions were less consistent. This finding raises a practical design question: should every replenishment decision pass through the same sequence of language-model roles? A retailer needs a correct and timely order, but some parts of the process already have an explicit rule or a structured input.

This chapter develops and evaluates selective delegation. The architecture uses the language model where supplier information needs interpretation, applies declared business policies through fixed rules, and checks the proposed order before release. Its contribution is the design of these responsibilities and the evidence about their consequences. LangGraph provides the software framework; using the framework itself is not presented as the original research contribution.

The additional research question is: can selective delegation improve the reliability and computational efficiency of an LLM-agent replenishment system while preserving service and simulated cost performance? The comparison changes the architecture while keeping the model, forecasts and numerical planning tool constant.

## 2. How the architecture works

The supplier-intake component first examines the format of the incoming message. A complete table in the declared format is parsed directly. Supplier prose is passed to the language-model reader. A malformed declared table requests review. The parser reads the message itself; it does not fill missing values from the authenticated reference used for verification.

The extracted fields are then checked against the current supplier record. This record contains delivery and ordering terms, rather than future customer demand. A policy router applies the declared business instruction: an active promotion prioritises availability, while routine trading and supplier disruption use the balanced policy. Unknown promotion status prevents automatic release. The router does not infer a priority from the experiment's future sales.

The shared numerical tool calculates the order. Deterministic checks verify its quantities against the budget, supplier capacity, carton size and minimum-order rules. Routine valid decisions proceed without a separate LLM critic call. Failed or unknown conditions invoke the exception-review path and hold the action. A model approval cannot override a failed check. Review requests are recorded; the experiment does not simulate a human resolving them.

[[FIGURE:selective_architecture]]

LangGraph implements this process as an explicit state graph with conditional edges. The main nodes cover intake, extraction, source verification, priority routing, constrained planning, action validation, review and release. Each decision record includes the nodes actually visited, the reason for delegation, the extracted information and the released quantity. The fixed comparison also runs through LangGraph, so the study does not confound the new architecture with the mere introduction of the framework.

## 3. Experiment design

The experiment includes thirty selected M5 series and thirty selected FreshRetailNet-50K series, labelled RetailNet. Each dataset is evaluated in two seven-day windows under routine trading, supplier disruption and promotion. Thirty new simulation seeds produce a total of 1,080 policy runs. Every matched case uses the same starting-stock rule, demand realisation and supplier opportunities across workflows.

Three workflows are compared. The fixed architecture calls the supplier reader, LLM coordinator and LLM critic on every decision. The selective architecture uses the conditional process described above. The structured-information reference uses the same numerical planner with already prepared current supplier fields and no LLM. This reference helps identify whether an improvement comes from planning, interpretation or the decision about which component performs a task.

All workflows use the same previously fitted, past-only LightGBM forecasts and the same constrained-order tool. The language model remains pretrained Qwen2.5 1.5B, running locally through Ollama on the four-CPU Linux cloud instance with 32 GiB of memory and no GPU. It was not trained or fine-tuned for this experiment. LangGraph 1.0.10 coordinates the workflow. Generation settings, role prompts and worked examples are unchanged from the fixed system.

Development checks used invented panels and separate development seeds. Eleven automated checks and live LangGraph integrations passed before the main protocol was frozen. Every main model response is fresh and recorded; no previous answer is loaded and no response cache or retry is used. The workflows' execution order is counterbalanced to reduce systematic timing advantages.

The registered assessment asks for at least 50% fewer model calls, lower mean decision time, preserved or improved priority accuracy without committed-action violations, and preservation of inventory outcomes. For the last criterion, the lower service-change bound must be greater than -0.10 percentage points and the upper cost-change bound must be below +0.5%. These are study tolerances, not retailer-approved targets. Paired uncertainty intervals describe thirty simulated seeds conditional on the chosen weeks; they do not estimate a retailer population effect.

## 4. Main results

The architecture met all four registered success conditions in both datasets. The table summarises the measured outcomes. Fixed and selective values are shown together to make the comparison easy to follow. A negative cost change favours the selective workflow. Costs remain synthetic inventory operating-cost indices, not realised financial savings.

[[TABLE:headline]]

### 4.1 Fewer model calls and faster decisions

The fixed workflow made 7,560 primary model calls, compared with 1,680 for selective delegation, a reduction of 77.78%. The reduction follows from skipping routine coordinator and critic calls and using the declared parser for supplier tables. It is an architectural saving, rather than evidence that the model generated answers more quickly or became more capable.

Mean decision time changed from 3.82 to 1.72 seconds in M5, and from 4.07 to 1.83 seconds in RetailNet. These represent measured reductions of 54.79% and 54.93%, respectively. The measures include graph orchestration and numerical planning on this instance. They do not measure employee time or production economics.

[[FIGURE:model_calls]]

[[FIGURE:decision_time]]

### 4.2 Business-priority reliability

Priority accuracy changed from 99.76% to 100.00% in M5, and from 86.90% to 100.00% in RetailNet. On active promotion days, the corresponding values were 99.00% and 100.00% for M5, and 45.00% and 100.00% for RetailNet.

This measure evaluates agreement with the declared business policy. It does not prove that the policy is commercially optimal. The improvement, where present, comes from implementing that instruction explicitly instead of asking the model to choose it repeatedly. Supplier extraction accuracy is reported separately in the diagnostics, so a successful priority decision cannot conceal an incorrect supplier field.

Exact supplier-information accuracy was 100.00% for the fixed workflow and 100.00% for selective delegation in M5. The corresponding RetailNet values were 100.00% and 100.00%. These figures include the current budget and all supplier terms and concern the controlled message corpus.

[[FIGURE:priority_accuracy]]

### 4.3 Service, cost and fresh-stock outcomes

Relative to the fixed architecture, the selective workflow changed M5 fill rate by +0.00 percentage points and its operating-cost index by -0.02%. The paired comparison did not establish a service improvement within the simulated weeks. The paired comparison did not establish a lower primary cost index.

For RetailNet, fill rate changed by +0.24 percentage points and the operating-cost index by -1.18%. The paired comparison established a service improvement within the simulated weeks. The paired comparison also established a lower primary cost index. These effects concern a change between two workflows already using the same strong planner, and should be kept distinct from the earlier comparison with conventional ordering.

[[FIGURE:inventory_effects]]

RetailNet also requires attention to waste. Its hypothetical three-day FIFO process means that a stronger availability priority can change the amount of stock that expires. The expiry graph reports all three situations, rather than assuming that a better service or cost outcome must also mean less waste. These expiry results depend on the simulated stock-life assumption; they are not observed disposal quantities from the dataset publisher.

The selective workflow's overall RetailNet expiry share was +0.08 percentage points different from the fixed workflow. In this study, the increase was concentrated in promotion handling. The lower primary cost index therefore coexisted with a small increase in waste, making the service–waste trade-off explicit.

[[FIGURE:retailnet_expiry]]

The selective workflow recorded 0 committed-action constraint violations and 0 review requests in the main grid. Failed-condition behaviour was checked separately during development. No unresolved operational exceptions arose in the primary study, so those tests support the checks' implementation rather than establishing performance during live exception handling.

## 5. Assessment and attribution

The architecture hypotheses are separate from the dissertation's earlier hypotheses about the complete replenishment package. Their results are stated below using the criteria frozen before this main evaluation.

[[TABLE:hypotheses]]

Every selective-workflow order matched the structured-information planner in the main study. The new architecture therefore connected the tested language inputs to the reference planning behaviour without an additional numerical-performance advantage over that reference. The structured reference therefore remains essential to interpretation. Any gain over the fixed workflow can be explained by how known policies are applied and how unnecessary calls are avoided; it should not be attributed to a more powerful forecast, a different optimisation method or training of the language model.

The engineering contribution is a tested allocation of decision responsibilities: language interpretation for the tested prose, direct parsing for the declared tables, explicit priority rules and verifiable release conditions. Local graph traces make that allocation inspectable. The study evaluates this design against a matched fixed workflow rather than treating more agent conversations as a measure of success.

## 6. Business relevance and limitations

For managers, the design offers a way to use language assistance where communication creates work while retaining established numerical controls. Fewer model calls and shorter processing time can improve technical feasibility on modest infrastructure. Whether this translates into a useful commercial return requires a separate assessment of integration, maintenance and employee checking effort.

The architecture was motivated by previously inspected diagnostics. New simulation seeds and fresh model calls do not make the historical weeks unseen research holdouts. The evidence covers thirty selected series per dataset, controlled supplier messages, fixed declared policies and short simulated horizons. It does not establish performance across all M5 products or all 50,000 RetailNet series. RetailNet quantities are normalised sales proxies, and the inventory costs and stock-life process are hypothetical.

The source-verification reference provides current authenticated supplier fields to all workflows. Real deployment would need equivalent access to reliable operational records. The primary study does not measure human review or the handling of arbitrary conflicting messages. Correct routing under a known event flag is useful engineering evidence, but it is not evidence that the model independently understands every promotion or supplier exception.

## 7. Conclusion and next step

The architecture met all four registered success conditions in both datasets. The specific verdicts and uncertainty intervals determine where stronger claims about service or cost are justified. The main architectural contribution is selective delegation: deciding when an LLM is needed, when a declared rule is sufficient and when an action must be held.

The next step is a pilot with real supplier communications and measured staff review. It should retain the same planner, include unfamiliar message formats and incomplete instructions, and count the time needed to produce a correct input. Longer periods and realistic product lives would then test whether the architecture's efficiency and reliability persist under broader operating conditions.
