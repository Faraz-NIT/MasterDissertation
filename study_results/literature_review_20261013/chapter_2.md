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
