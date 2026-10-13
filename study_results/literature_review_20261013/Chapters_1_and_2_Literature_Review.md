# 1. Literature review: retail replenishment and the information behind the order

## 1.1 The business problem in the literature

Retail replenishment involves deciding what to order, when to order it and how much to buy. The decision looks straightforward when viewed as a calculation, but it brings together several competing business interests. Customers expect products to be available. Finance teams want to limit the money tied up in stock. Store teams need orders that fit their storage space and working routines. For fresh products, there is also a deadline: stock that remains unsold may lose value or become unusable. The literature therefore treats replenishment as a balance between service, inventory and operating costs, rather than a simple attempt to maximise sales (Zipkin, 2000; Nahmias, 1982).

A useful distinction runs through this research. Some studies ask what an optimal ordering policy should look like under specified assumptions. Others examine why actual ordering decisions differ from those policies. A third group investigates the quality of the information available to the decision-maker. These approaches address different parts of the same problem. A mathematically sound policy may work poorly if inventory records are inaccurate, while an experienced manager may struggle to make consistent decisions across a large product range. Understanding replenishment requires attention to the policy, the information and the organisation using them.

This chapter reviews these strands together. It begins with inventory theory and retail ordering behaviour, then considers data quality, demand forecasting, supply uncertainty and perishability. It also explains why M5 and FreshRetailNet-50K offer different perspectives on retail demand. The review is thematic: it compares the contribution and limitations of selected foundational studies, retail forecasting research and dataset publications. It does not claim to be an exhaustive or systematic review. Its purpose is to establish the business problem that an LLM-supported replenishment system would need to address.

## 1.2 Inventory theory: a strong foundation with practical boundaries

Inventory theory provides a clear starting point. Ordering too little creates the risk of lost sales, while ordering too much creates holding costs and, in some settings, waste. An ordering policy makes this trade-off explicit. It links expected demand, replenishment delays, existing stock and the cost of shortages to a decision about future supply. Zipkin (2000) brings these relationships together and shows why the appropriate policy depends on the operating environment. There is no single stock level that is best for every product and every retailer.

Clark and Scarf (1960) extend the discussion beyond an individual stock point. Their work on multi-echelon inventory demonstrates that ordering decisions at one stage of a supply chain cannot always be evaluated independently of decisions elsewhere. For a retailer, the implication is that availability at the store may depend on warehouse policy and upstream replenishment. Improving a local decision without considering these connections can move inventory or shortages to another part of the system. Their contribution is theoretical, however, and rests on the assumptions of the model. It should not be treated as evidence that every retail network can be managed through the same policy.

The strength of inventory theory is its discipline. It makes objectives and constraints visible and provides a way to evaluate alternatives consistently. Its practical boundary is that an operational model can only represent the information supplied to it. A planner may calculate a sensible order using a delivery time that has just changed, or recommend stock that the store cannot physically accommodate. These situations do not invalidate the underlying theory. They show that calculation and the collection of current business information are separate responsibilities.

This distinction matters for the later discussion of language models. A retailer already has established methods for calculating quantities. The more open question is how changing instructions, supplier messages and business priorities enter those calculations. The inventory literature consequently supports retaining a disciplined numerical planner while investigating whether another component can improve the information reaching it.

## 1.3 Retail ordering behaviour and the limits of standardisation

Actual store ordering does not always follow the recommendation produced by a replenishment system. Van Donselaar et al. (2010) examine ordering behaviour in retail stores and its implications for automated replenishment. Their work makes clear that implementation is an organisational issue as well as a modelling issue. Store employees make decisions within working routines and practical conditions that may not be fully reflected in a central system.

This evidence complicates a common assumption about automation: that removing human intervention necessarily improves the decision. A manual adjustment may reflect local knowledge about demand, stock presentation or operations. It may also introduce inconsistency. The relevant question is whether an adjustment adds useful information and whether its consequences can be evaluated. Treating every override as an error would overlook knowledge held by employees. Treating every override as valuable would make it difficult to distinguish informed judgement from habit.

The behavioural and theoretical literatures therefore complement each other. Inventory theory explains how an order can be justified against a defined objective. Research on store behaviour explains why a recommendation may not be followed. Together, they suggest that an effective system needs both a reliable calculation and a workable relationship with its users. A technically strong recommendation has limited value if employees cannot understand it, supply the information it needs or resolve exceptions.

For LLM-supported replenishment, the potential benefit is partly organisational. A language interface could make it easier to express an exception or ask why an order changed. That possibility follows from the problem identified in the retail literature; it is not a finding established by van Donselaar et al. (2010). Whether such an interface reduces work, improves compliance or captures useful local knowledge remains an empirical question. Its value should be assessed through the quality of decisions and the effort required to use it.

## 1.4 Information quality: correct numbers are only part of the requirement

Wang and Strong (1996) argue that data quality extends beyond accuracy. Information must also be suitable for its purpose, accessible and understandable to its users. This is particularly relevant to replenishment because a decision combines information from several sources. Sales history describes past transactions, inventory records describe recorded availability, and supplier updates describe future delivery possibilities. Each can be accurate in its own terms while still being incomplete or unsuitable for the order being considered.

DeHoratius and Raman (2008) provide empirical evidence that inventory record inaccuracy is a substantial retail problem. Their study draws attention to the difference between recorded stock and physical stock. Kang and Gershwin (2005) examine mechanisms through which information inaccuracy and stock loss affect inventory performance. Read together, these studies show why the quality of an ordering rule cannot be judged independently of the stock information on which it acts. A system that believes units are available may postpone replenishment even when customers face an empty shelf.

The studies contribute different forms of evidence. Wang and Strong (1996) offer a broader understanding of what users need from information. DeHoratius and Raman (2008) document an operational problem in retail records. Kang and Gershwin (2005) explain consequences within inventory systems. The combined lesson is stronger than the statement that a retailer needs clean data. Information must describe the right situation at the time a decision is made, and the system must recognise where that description is uncertain.

This creates a boundary for language-based assistance. Reading a supplier message may help extract a revised delivery date, but it does not verify the physical stock in a store. Rephrasing an inaccurate inventory record does not make it accurate. The relevant contribution of an LLM would be to improve the handling of information that is expressed in language, while remaining dependent on separate controls for stock accuracy and source reliability. A useful design makes these responsibilities visible rather than allowing fluent communication to obscure them.

## 1.5 Sales are not always the same as demand

Retail forecasting often begins with sales history, but sales and demand are not interchangeable. When a product is unavailable, a customer may leave without buying it. The transaction record captures the purchase that occurred, not the purchase that would have occurred had stock been available. Nahmias (1994) examines demand estimation in lost-sales inventory systems and establishes why availability matters when interpreting observed sales.

The managerial consequence is a possible feedback problem. A stockout can reduce recorded sales; a forecast based on those sales can then support a smaller order; the smaller order can create further stockouts. Low sales may therefore indicate weak demand, restricted availability or a combination of both. Distinguishing these explanations is important before concluding that a product needs less stock. It is also important when evaluating a replenishment policy, because an apparent reduction in inventory may come at the expense of purchases that were never recorded.

FreshRetailNet-50K makes this issue particularly visible. Wang et al. (2025) introduce a fresh-retail dataset with stockout annotations for research on censored demand and forecasting. The accompanying dataset card describes hourly stock-status information alongside sales and contextual variables (Dingdong-Inc., 2025). These records offer a way to identify periods in which sales may be constrained by availability. They do not directly reveal every customer's unmet demand. Any reconstruction of that demand still requires assumptions or a model.

The literature consequently calls for careful language about what is observed. Forecasting sales, estimating unconstrained demand and simulating customer demand are different activities. A study may legitimately use observed sales as its evaluation target, but it should acknowledge the resulting boundary. This is especially relevant to comparisons between M5 and FreshRetailNet-50K: differences in availability information change what the researcher can know about a low-sales period. They should not be interpreted simply as differences in the intelligence of the ordering system.

## 1.6 Forecasting methods and their relationship to replenishment

Forecasting research has long recognised that retail demand is difficult to predict consistently. Some products sell frequently, while others have many periods with no sales. Croston (1972) addresses intermittent demand by separating the size of non-zero demand from the intervals between demand events. Syntetos and Boylan (2005) subsequently examine the accuracy of intermittent-demand estimates and introduce a correction to the Croston approach. These studies show the importance of matching a method to the demand pattern rather than assuming that one technique will perform equally well across an entire product range.

More recent research considers methods that learn relationships across products and explanatory variables. The M5 accuracy competition provides an important benchmark for large-scale retail forecasting. Makridakis et al. (2022) discuss its results and the strong performance of machine-learning approaches within that setting. LightGBM, introduced by Ke et al. (2017), is a computationally efficient tree-based learning method relevant to this family of approaches. The LightGBM paper explains a modelling technique; the M5 competition provides evidence about forecasting performance on a particular retail benchmark. Neither, by itself, establishes the profitability of a replenishment system using that technique.

This distinction is central to the review. Forecast accuracy measures how closely predictions match the chosen target. Replenishment performance measures the consequences of decisions made using those predictions. A forecast with a lower average error may still lead to disappointing service if an order ignores delivery delays or budget constraints. Conversely, a policy can protect service by carrying more stock, even when the forecast itself has not improved. That protection has a cost which forecast accuracy alone does not capture.

Gneiting and Raftery (2007) offer a foundation for evaluating probabilistic forecasts through proper scoring rules. Their work supports considering uncertainty, rather than relying solely on a single predicted value. For replenishment, the business relevance is that shortage risk depends on a range of possible demand outcomes. However, evaluating a probability forecast and choosing an inventory policy remain separate tasks. The forecasting literature supports better inputs to the decision, while inventory theory supplies the framework for acting on those inputs.

## 1.7 Lead times, shared constraints and the bullwhip effect

Demand is not the only source of uncertainty. A retailer must also consider when an order will arrive and whether the requested supply will be available. Lee et al. (1997) explain how demand information can become distorted as it moves through a supply chain, contributing to the bullwhip effect. Chen et al. (2000) analyse the influence of forecasting, lead times and information in a simple supply-chain setting. Their work connects ordering behaviour with the amplification of variation upstream.

These studies broaden the meaning of a good replenishment decision. An order may address an immediate store shortage while also creating unstable requirements for suppliers. Delivery delays can increase the period that inventory must cover, and repeated changes in orders can make planning more difficult elsewhere in the chain. Better visibility can help, but its effect depends on how organisations translate information into orders. More information is useful only if the decision process uses it appropriately.

There is also a practical allocation problem. When several products share a purchasing budget or supplier capacity, each cannot be replenished independently. Giving every product its individually preferred order may exceed the resources available. The retailer must make priorities explicit and apply them consistently. Clark and Scarf (1960) address coordination through a formal inventory framework, while Lee et al. (1997) and Chen et al. (2000) examine information and order variability. Together, they highlight different reasons why local ordering decisions need a wider view.

This literature gives supplier communications an operational role. A message about a delayed delivery is relevant because it changes the assumptions behind the order, rather than merely providing useful background. A language model could help make that change available to the planner. The potential benefit still depends on correctly identifying the message's scope, timing and authority. These requirements connect the supply-chain literature with the agent and automation research considered in Chapter 2.

## 1.8 Perishability and the complementary value of M5 and RetailNet

Nahmias (1982) reviews perishable inventory theory and shows why limited product life changes the ordering problem. For a durable item, stock carried into the next period can still satisfy later demand. For a fresh item, that option may disappear. The retailer must therefore consider both a possible shortage and the possibility that unsold stock will expire. Increasing availability by increasing stock can improve one outcome while worsening another.

Perishability also changes the information needed for planning. A total inventory count does not necessarily describe how long the stock will remain useful. Age and remaining life may matter as much as quantity. This makes a fresh-retail decision different from a general forecasting exercise. Sales history can inform expected purchases, but it does not by itself provide product-level shelf life, the age of current stock or the retailer's actual disposal cost. Those elements must come from operational records or be clearly identified as modelling assumptions.

M5 and FreshRetailNet-50K contribute complementary evidence. M5 provides a well-established retail forecasting benchmark with multiple product and store series (Makridakis et al., 2022). FreshRetailNet-50K focuses on fresh retail and makes stockout-related information more explicit (Wang et al., 2025; Dingdong-Inc., 2025). In this dissertation, the shorter label RetailNet refers to FreshRetailNet-50K. The labels distinguish the two evidence sources; they do not imply that the datasets have identical measurement systems or represent the same retail environment.

Using both can test how sensitive a decision approach is to the characteristics of the available evidence. It does not justify a direct comparison of absolute sales quantities or costs without considering how those quantities are defined. The FreshRetailNet dataset card states that sales amounts are globally normalised (Dingdong-Inc., 2025). Any interpretation in terms of physical units or financial returns therefore requires additional justification. More broadly, success on either benchmark is evidence within that setting, not proof of performance across all retailers.

## 1.9 What the replenishment literature establishes

The literature reviewed in this chapter supports three connected conclusions. First, replenishment is a constrained business decision in which service, inventory and waste need to be assessed together. Second, forecasting is an important input, but the quality of the order also depends on inventory visibility, delivery information and the way priorities are applied. Third, the same policy can behave differently across retail settings because demand patterns, information quality and product life differ.

These conclusions provide a specific entry point for LLM agents. Established numerical methods already address much of the calculation. A less structured part of the workflow is the translation of changing business information into inputs that those methods can use. The research question is therefore whether language-based assistance can improve that connection reliably and at a reasonable cost. Chapter 2 reviews the emerging agent literature and considers what would count as convincing evidence of such a contribution.

# 2. Literature review: LLM agents and decision support for replenishment

## 2.1 The potential contribution of language models

The replenishment literature identifies a decision process that depends on both numerical evidence and business information. A forecast estimates future sales, while a supplier message may change what can be delivered. A store instruction may alter the priority given to a product. The attraction of a large language model lies in its ability to work with the language through which these updates are often expressed. It may help turn a written request or operational message into information that a planning system can use.

Li et al. (2023) investigate this connection in supply-chain optimisation through OptiGuide. Their work links natural-language questions with optimisation tools and supports business-oriented what-if analysis. The contribution is a way to interact with a decision model, rather than evidence that a language model should replace the model's numerical calculations. This division is relevant to replenishment: a manager can ask about a delivery change in familiar language while a separate tool evaluates its implications under defined constraints.

The potential business value is accessibility. Employees may be able to communicate relevant information without learning a specialist interface, and managers may find it easier to explore alternatives. These are plausible benefits, but they need separate evaluation. A convincing conversational answer is not sufficient evidence of a correct plan. Similarly, an interface that looks easier to use may still increase checking effort if users must repeatedly verify what it extracted.

The literature therefore supports a narrower, more testable proposition than a general claim that LLMs improve replenishment. Language models may help connect business communication with established planning methods. Whether that connection creates value depends on extraction accuracy, the reliability of the downstream calculation and the time needed to identify and correct mistakes.

## 2.2 From a conversational model to a tool-using agent

A conversational model produces a response to a prompt. An agent extends that arrangement by interacting with tools or an environment as part of a task. Yao et al. (2023) introduce ReAct, which combines reasoning and action so that a model can use observations from the environment while working towards an answer. The study demonstrates the approach in benchmark tasks involving question answering and interactive environments. It provides evidence for the usefulness of connecting language-model reasoning with external actions.

ReAct is relevant because replenishment also requires interaction with information outside the model. The current stock, delivery commitments and purchasing limits should come from operational sources. They cannot be assumed to be known from the model's pre-training. A tool-connected system can obtain those inputs and pass them to a planner. The model's role becomes one of selecting or coordinating an action within a defined process, rather than generating every answer from its own stored knowledge.

However, the step from benchmark performance to operational purchasing is substantial. A successful action in a research environment does not establish that an agent will interpret a live supplier instruction correctly or maintain compliance over months of ordering. ReAct supports a general design principle; it does not provide direct evidence of replenishment performance on M5 or RetailNet. The retail application requires its own evaluation and a clear definition of what the agent is allowed to do.

For this reason, an agent should be described through its responsibilities rather than through the label alone. Does it retrieve information, propose a change, call a calculation tool or release an order? These are different levels of involvement. A system that reads a message and prepares a proposal may offer substantial support even when it has no authority to place the order. Defining the action makes both the expected benefit and the required evaluation clearer.

## 2.3 Multiple agents, division of work and coordination

Wu et al. (2023) introduce AutoGen as a framework for applications built around conversations between multiple agents. The framework allows different combinations of language models, tools and human participation. Its relevance is that a complex task can be divided into roles, with an explicit pattern of communication between them. Compared with the tool interaction emphasised in ReAct, this approach draws attention to how separate contributions are coordinated across a workflow.

In replenishment, a division of work might distinguish reading supplier information, interpreting a business priority and checking a proposed order. The organisational analogy is familiar: purchasing, planning and review do not perform the same task. Distinct agent roles could make responsibilities easier to understand and create records of how information moved through the process. This is an application of the multi-agent idea, not evidence that adding more agents will automatically improve inventory outcomes.

The potential disadvantage is additional coordination. Each stage may introduce a misunderstanding, a delay or an unnecessary model call. If an early role interprets a delivery date incorrectly, later roles may repeat the error. Agreement between agents is especially weak evidence when they use the same model and the same source material. Different prompts do not necessarily create independent judgement. A separate reviewing role can be useful, but its conclusions still require checks against records and constraints.

The comparison between ReAct, AutoGen and OptiGuide suggests that the agent literature addresses several related questions. ReAct asks how reasoning can interact with actions and observations. AutoGen provides a framework for coordination between roles. OptiGuide connects language with supply-chain optimisation. For a retail study, the relevant choice is the simplest arrangement that performs the required work and can be evaluated clearly. The number of agents is a design choice, while service, cost, reliability and user effort are outcomes.

## 2.4 Automation, managerial control and appropriate trust

The literature on human interaction with automation provides an important counterweight to the enthusiasm surrounding agents. Parasuraman and Riley (1997) distinguish useful adoption from misuse, disuse and abuse of automation. Their analysis shows that the relationship between people and a system can affect performance. Excessive reliance can lead users to accept an incorrect recommendation, while distrust can prevent them from benefiting from a reliable one.

Parasuraman et al. (2000) develop a framework that separates types and levels of automation across information acquisition, analysis, decision selection and action implementation. This separation is particularly helpful for replenishment. A retailer can automate the reading of a routine message without delegating unrestricted purchasing authority. It can also automate a calculation while requiring approval for an unusual order. Automation need not be an all-or-nothing choice.

Applied to LLM agents, this literature suggests that permission should follow the reliability of the task and the consequences of an error. Extracting an item identifier from an approved message is different from deciding to exceed a purchasing limit. A bounded system can let the model propose an interpretation while rules check the source, required fields and business limits before an action is accepted. Those checks are a design implication drawn from the automation literature, rather than a replenishment architecture directly tested in the cited human-factors studies.

Managerial responsibility also remains relevant. When an order is wrong, the retailer needs to identify whether the cause was the input, the interpretation, the numerical plan or the approval process. A generic statement that the AI made the decision provides little help. Clear responsibilities and visible decision records support diagnosis and appropriate trust. They also allow the retailer to expand automation selectively when evidence supports it, rather than treating the introduction of an agent as an immediate transfer of all authority.

## 2.5 Explanations, evidence and the limits of model review

Language models can generate clear explanations, but clarity does not guarantee that an explanation faithfully represents how an answer was reached. Turpin et al. (2023) examine unfaithful explanations in chain-of-thought prompting. Their findings caution against treating a model's account of its reasoning as a complete or reliable description of the influences behind its response.

For replenishment, this distinction is practical. A statement such as “the order increased because delivery will be late” may be understandable, but it should be checked against the actual supplier record and the planner's inputs. An explanation is useful when it directs the user to verifiable evidence. It is less useful when it offers a plausible narrative that cannot be reconciled with the decision record. The manager needs to know what changed, which source authorised the change and whether the resulting order respected the rules.

Turpin et al. (2023) do not establish that every language-model explanation is incorrect. Their contribution is to show why explanations require caution as evidence. This connects with the data-quality literature reviewed in Chapter 1: understandable information is valuable, but it must also be accurate and appropriate for the task (Wang & Strong, 1996). Fluency addresses only part of that requirement.

The resulting evaluation should distinguish several outcomes. A model can produce a well-formed response that contains the wrong delivery time. It can extract the delivery time correctly but select an inappropriate priority. A reviewing role can approve a plan whose quantity was already constrained correctly by a numerical tool. In each case, the visible conversation may look successful while the underlying contribution differs. Assessment should therefore follow the information and actions themselves, including proposed changes that were rejected, rather than relying only on a final narrative or the absence of an invalid order.

## 2.6 Local models and the practical conditions of adoption

The model and the software running it are separate components. The Qwen2.5-1.5B-Instruct model card describes a compact instruction-following language model (Qwen Team, 2024). Ollama provides software interfaces for running supported models and accessing their responses locally (Ollama, 2026). These publications document capabilities and access arrangements; they are not evidence that this model and software combination improves replenishment.

Local execution is nevertheless relevant to the business discussion. It can allow an organisation to run a model within infrastructure it controls and can reduce dependence on an external inference service. The corresponding costs include maintaining the environment, providing enough computing capacity and managing model versions. A locally hosted model may have no separate charge for each call, but its use still consumes time, hardware and operational effort.

Model size also involves a trade-off. A compact model may make experimentation and routine processing feasible on modest equipment, yet may struggle with some instructions or ambiguous messages. A larger model may improve particular tasks while requiring more resources. Documentation alone does not establish which choice is appropriate. The relevant comparison concerns the quality and speed of the specific work the retailer needs performed.

It is also necessary to distinguish inference from training. Using an existing instruction model to process retail messages does not mean that the retailer trained the model on its sales data. Fitting a separate demand forecaster is another activity. A dissertation should report these distinctions and the computing environment in its methodology, because they affect reproducibility and the interpretation of performance. From the literature review, the wider implication is that adoption needs an operational assessment as well as a model assessment: the system must be affordable, maintainable and responsive enough for the ordering process.

## 2.7 How to evaluate the contribution of an LLM agent

Hevner et al. (2004) describe design science in information systems as research that develops and evaluates an artefact addressing a relevant problem. This perspective is suitable for agent-supported replenishment because the contribution is a working decision process, rather than a language model in isolation. The central question is whether the arrangement performs useful business work under conditions that are stated clearly.

An important challenge is attribution. If a new system combines a stronger forecast, better supplier information and a constrained planner with an LLM, improvement over a simple ordering rule cannot be assigned entirely to the LLM. Any of those components may explain the difference. A comparison with conventional ordering answers whether the complete arrangement is useful. A comparison with the same planner and equivalent structured information, supplied without the LLM, addresses a narrower question about the language component's contribution. This comparison is a methodological implication of the literature synthesis, not a result already established by the studies reviewed.

The narrower comparison also has a limitation. Equivalent structured information may require manual work in practice. Supplying it directly in an experiment can help isolate decision quality, but it does not measure the effort saved by extracting it from text. A field evaluation would need to examine both dimensions. A language model could match the numerical outcome of an existing process while reducing preparation time, or produce a better simulated outcome while creating an unacceptable burden of checking and maintenance.

Performance measures should consequently cover service, resource use and reliability. Inventory theory supports examining shortages and holding costs together (Zipkin, 2000), while perishability adds waste to the assessment (Nahmias, 1982). Agent evaluation should also measure whether information was interpreted correctly, whether actions complied with business rules and how long the process took. Repeated tests are needed to understand consistency. Results should be reported separately for M5 and RetailNet, with uncertainty and modelling assumptions made explicit, because the two datasets support different interpretations of observed sales and availability.

## 2.8 Research gap and the position of this dissertation

The reviewed literature provides a substantial foundation, but the evidence is distributed across research areas. Inventory studies explain the trade-offs in ordering. Retail and data-quality studies show why real decisions can depart from a model's recommendation. ReAct and AutoGen demonstrate approaches to tool interaction and coordination, while OptiGuide brings language models closer to supply-chain analysis. The automation literature explains why authority and user reliance need careful design. Each strand contributes part of the argument; none alone establishes the business performance of the complete replenishment workflow considered here.

The gap identified in this review is therefore specific: the need to evaluate whether a bounded LLM agent can translate relevant business information into a replenishment process reliably, and whether the resulting benefits can be separated from those supplied by the numerical planner. In the literature reviewed, benchmark success and accessible explanations do not answer that question. Nor is a single improvement in service sufficient when it may be achieved through more stock, greater waste or a more powerful planning tool.

The contribution is intended to be informative rather than universal. A controlled study can test decision quality and reliability in defined situations; it cannot establish customer satisfaction, employee acceptance or realised financial returns without evidence from deployment. The literature nevertheless gives a clear basis for investigating LLM agents: they may help a retailer connect changing communication with disciplined planning. The following chapters develop and evaluate that proposition, with the model, computing environment and experiment assumptions reported separately from the findings.

## 2.9 Research aim and research questions

The research aim is to evaluate whether a locally run LLM-agent workflow is useful for retail replenishment, identify the contribution of the language model within that workflow, and examine how its performance changes across M5 and FreshRetailNet-50K.

### Main research question

To what extent can an LLM-agent replenishment system improve retail service and simulated cost efficiency, and which benefits are attributable to the LLM rather than to the numerical planner?

### RQ1. Does the complete system improve replenishment?

Compared with conventional ordering, does the complete LLM-agent workflow achieve a higher fill rate and a lower simulated operating cost on M5 and RetailNet? This question concerns the value of the whole system, including its forecasting, information handling and constrained planning.

### RQ2. What additional value does the LLM contribute?

Compared with the same numerical planner receiving equivalent structured information without an LLM, does the LLM-agent workflow improve fill rate or simulated operating cost? This question separates a system-level improvement from an improvement that can be attributed to the language component.

### RQ3. Which agent tasks are performed most reliably?

How accurately does the system extract supplier facts and select business priorities, and how do these two forms of accuracy compare? This question assesses the work performed by the agents, rather than assuming that a successful final order means every intermediate interpretation was correct.

### RQ4. How does performance differ between M5 and RetailNet?

Does the improvement over conventional ordering differ between the two datasets? This question examines context rather than assuming that one performance result applies equally to general retail sales and fresh retail. Differences must be interpreted alongside the datasets' information, units and inventory assumptions.

## 2.10 Research hypotheses and assessment criteria

The hypotheses translate these questions into claims that the evidence can support or challenge. They provide an analytical framework for interpreting the study; they are not presented as a preregistered confirmatory protocol. Each comparison must be assessed on its own, and favourable evidence for the complete workflow does not automatically establish a benefit from the LLM itself.

### H1. The complete workflow improves on conventional ordering

H1a: The complete LLM-agent workflow achieves a higher fill rate than conventional ordering.

H1b: The complete LLM-agent workflow achieves a lower simulated operating cost than conventional ordering.

These hypotheses follow from combining current business information with constrained planning, as motivated by the inventory, information-quality and tool-supported decision literature (Zipkin, 2000; Wang & Strong, 1996; Li et al., 2023). They concern the package as a whole. H1a and H1b are evaluated separately for M5 and RetailNet: a service improvement alone does not establish a cost improvement.

### H2. The LLM adds value beyond the same numerical planner

H2a: The LLM-agent workflow achieves a higher fill rate than the same planner receiving equivalent structured information without an LLM.

H2b: The LLM-agent workflow achieves a lower simulated operating cost than that same-planner comparison.

H2 is the more demanding test of the LLM's incremental contribution. The agent literature makes the proposition worth investigating, but it does not guarantee either result (Yao et al., 2023; Li et al., 2023). If performance is equivalent or worse, the evidence does not support an additional operational benefit from the LLM on the measured outcomes. Such a finding would still leave open benefits, such as reduced information-entry time, that require separate measurement.

### H3. Fact extraction is more reliable than priority selection

The agents achieve higher accuracy when extracting explicit supplier facts than when selecting the required business priority.

This hypothesis distinguishes a narrowly specified extraction task from a task requiring interpretation of instructions and priorities. It is motivated by the need to evaluate individual contributions and verify model outputs, rather than accepting fluent responses as evidence of correctness (Turpin et al., 2023; Wang & Strong, 1996). Accuracy means agreement with the authenticated supplier record or the scenario's predefined priority, not agreement with another agent's answer. The comparison concerns these controlled tasks; it does not establish that all extraction tasks are easier than all prioritisation tasks.

### H4. The size of the benefit depends on the retail setting

The improvement over conventional ordering differs between M5 and RetailNet in fill-rate change, proportional simulated-cost change, or both.

This is a non-directional hypothesis: it does not assume in advance that either dataset must produce a larger gain. It follows from the different information and operating problems highlighted by the retail forecasting and perishable-inventory literature (Makridakis et al., 2022; Nahmias, 1982; Wang et al., 2025). A difference would describe context sensitivity within the study. It would not, by itself, establish perishability as the cause because the datasets differ in other respects as well.

### Definitions and interpretation

Fill rate is the proportion of demand served under the study's stated demand definition. A fill-rate improvement is reported in percentage points. Simulated operating cost combines the modelled cost components; its change is reported relative to the comparator, rather than being described as realised profit. Task accuracy is the proportion of decisions matching the specified reference. These definitions keep service, financial proxies and information handling distinct.

The results should state whether each hypothesis is supported, not supported or inconclusive within the study's scope. Repeated matched comparisons and uncertainty estimates help distinguish a consistent effect from a small or unstable difference. H4 requires a comparison of the changes between datasets; observing a favourable result in one dataset and an inconclusive result in the other does not alone prove that the effects differ. If an appropriate comparison is unavailable, H4 should remain exploratory. This framework allows the dissertation to recognise useful LLM-agent performance without overstating what the evidence establishes.
