# From agent behavior to measurable correctness

## A practical evaluation workflow with OCI Generative AI and Langfuse

An agent demonstration becomes more useful when its behavior can be checked repeatedly against explicit expectations. This project shows how to build that feedback loop: define a task, create representative inputs, establish correct answers, run the agent, and inspect the evidence behind its successes and failures.

The example is **Automotive Express Order offer selection**. Its scope is deliberately narrow, allowing us to verify a business decision precisely while developing an evaluation pipeline that can be adapted to other tasks.

The implementation, synthetic data, specifications, and instructions are available in the [Agent Evals GitHub repository](https://github.com/luigisaetta/agent-evals).

## 1. Why evaluations matter for agentic solutions

An agentic solution combines several sources of behavior: model responses, instructions, application code, tools, retrieved information, and execution state. A final answer can look convincing even when one of the underlying decisions is wrong. A change that improves one scenario can also break another.

Evaluations make the expected behavior concrete. They help answer questions such as:

* Does the agent apply the business rules in the correct order?
* Does it respect constraints when an attractive alternative violates them?
* Does a new prompt or model improve the same set of cases?
* Is a failure caused by the model, the output contract, the evaluator, or infrastructure?
* Which previously correct cases became incorrect after a change?

This creates a practical development cycle: establish a baseline, make a focused change, rerun comparable cases, and inspect differences before accepting the change.

### Software tests and behavioral evaluations provide different evidence

Software tests check that the implementation behaves as intended. For example, a unit test can verify that a scoring function returns zero for an incorrect answer or that the runner waits between requests.

Behavioral evaluations execute the model-backed task and measure whether it produces the expected business result. Passing the software tests does not establish that the model makes the right decisions. Conversely, one successful model response does not prove that the runner handles invalid output or network errors correctly.

The project therefore keeps offline correctness tests and live model experiments distinct. Both contribute evidence, but they answer different questions.

### A task-level evaluation is a useful first boundary

A complete agent may monitor events, gather information, call several tools, and execute a business action. Evaluating a well-defined component first helps isolate the behavior under investigation and gives failures a clear interpretation.

Task-level correctness is one part of a broader evaluation strategy. A production agent would also need checks for its tool execution, permissions, workflow state, recovery behavior, and final business outcomes. This demo measures the offer-selection decision only.

## 2. What we wanted to demonstrate

Our objective was to create a working example of evaluations applied to an agent, or to a specific task within an agent, using an explicit and independently checkable success criterion.

The hypothetical company manufactures cars at multiple plants. When a plant's available stock of a part decreases, an **Express Order** is initiated. Suppliers are invited to submit offers, and the agent must identify the best offer for that request.

The agent receives:

* The required part ID.
* The plant's delivery city.
* An exclusive delivery deadline.
* Six structured supplier offers.
* Business rules written in a separate natural-language file.

Each offer contains an offer ID, supplier ID, part ID, delivery city, delivery date, and total cost in euros. Supplier identity is recorded but does not influence the current ranking rules.

The model returns a structured answer:

```json
{"selected_offer_id": "<identifier of one supplied offer>"}
```

The evaluation succeeds when that identifier exactly matches the expected identifier stored in the dataset. This criterion does not require another model to judge the answer.

The [task specification](https://github.com/luigisaetta/agent-evals/blob/main/specs/offer-selection.md) defines the contract. Stock monitoring, order initiation, invitations, offer collection, purchase-order placement, and delivery execution remain outside the evaluated boundary.

## 3. Turning business rules into an evaluation contract

Before constructing the dataset, we defined the meaning of the best offer:

1. The offered part must exactly match the requested part ID.
2. The delivery city must exactly match the requested city.
3. The delivery date must be strictly earlier than the deadline. Delivery on the deadline is excluded.
4. Among eligible offers, the lowest total cost wins.
5. Equal lowest costs are resolved by the earliest delivery date.

Eligibility is applied before ranking. A lower price cannot compensate for the wrong part, the wrong destination, or a missed deadline. An earlier delivery cannot compensate for a higher price when both offers are eligible.

Dates use a calendar-date representation, and all costs are expressed in euros. The initial dataset has a unique winner in every case; no-eligible-offer cases and ties remaining after both price and date comparisons require further policy and are excluded.

These decisions are written in the [versioned rule file](https://github.com/luigisaetta/agent-evals/blob/main/rules/offer-selection.md). Making them explicit gives both the model prompt and the reference evaluator a common business specification.

## 4. How we built the demo

The implementation followed a sequence that made each later step verifiable:

| Step | What we built | Why it matters |
| --- | --- | --- |
| Define the task | Input/output contract, business rules, success criterion | Establish what correctness means before measuring it |
| Build the reference selector | Deterministic filtering and cost/date ranking | Produce expected answers independently of the model under test |
| Create catalogs | Suppliers, parts, hypothetical plant destinations | Give synthetic cases consistent identifiers and plausible content |
| Generate the dataset | Scenario-driven requests and offers, labels, splits and manifest | Exercise specific behaviors with reproducible test inputs |
| Implement the model task | Prompt construction, OCI Responses call, strict output parsing | Test the LLM's decision using a clear response contract |
| Build the runner | Sequential calls, pacing, diagnostics, progress and local artifacts | Make experiments repeatable and failures inspectable |
| Integrate Langfuse | Hosted dataset items, experiments, generation traces and scores | Connect aggregate results to individual executions |
| Separate the task adapter | Domain validation, prompt, parsing and scoring in one module | Reuse the pipeline for another business task |

The [reference selector](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/selection.py) is a dataset-authoring and verification tool. It does not choose the answer on behalf of the LLM during an experiment. Evaluation startup reads the stored references and checks structure and provenance without recalculating the winners.

## 5. Generating the synthetic dataset

### 5.1 Start from consistent reference catalogs

We created three local JSON catalogs:

| Catalog | Records | Contents |
| --- | ---: | --- |
| Suppliers | 50 | Stable IDs and fictional supplier names |
| Parts | 100 | IDs, automotive part names and illustrative average unit costs in euros |
| Plant locations | 10 | IDs, countries and European capital names, including Rome |

The catalogs provide consistent references for case generation. They do not represent actual suppliers, commercial quotations, or company plants. Average part costs are generation inputs; the selection rules compare an offer's total cost, not the catalog average.

The data and its assumptions are documented in the [catalog directory](https://github.com/luigisaetta/agent-evals/tree/main/data/catalogs).

### 5.2 Generate scenarios deliberately

The dataset is generated by Python code, rather than by asking an LLM to invent both cases and correct answers. The generator constructs cases around specific rule interactions:

| Scenario | Cases | Behavior under test |
| --- | ---: | --- |
| All offers eligible, distinct costs | 10 | Select the minimum cost |
| Cheaper offer for the wrong part | 10 | Apply part eligibility before price |
| Cheaper offer for the wrong city | 10 | Apply destination eligibility before price |
| Cheaper offer on the deadline | 10 | Respect the exclusive deadline |
| Cheaper late offer | 10 | Reject delivery after the deadline |
| Two-way lowest-cost tie | 10 | Use the earlier delivery date |
| Three-way lowest-cost tie | 10 | Apply the same tie rule across more candidates |
| Cost versus faster delivery | 10 | Preserve cost as the primary ranking criterion |
| One-cent winning margin | 10 | Compare monetary amounts precisely |
| Mixed eligibility failures | 10 | Find the only eligible offer among cheaper distractors |

This gives **100 cases and 600 offers**. Every part is requested once, each plant city is requested ten times, and all suppliers appear. Some cases include multiple offers from the same supplier.

Offer totals are derived from catalog costs with synthetic variation and an illustrative express-delivery surcharge. Construction uses integer cents; the reference selector compares decimal monetary values. Dates are generated relative to a fixed origin, rather than the day the program runs.

The [generator source](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/generate_dataset.py) shows the scenario construction and reference-label calculation.

### 5.3 Establish and check ground truth

For every generated request, the deterministic selector validates the input, removes ineligible offers, and ranks the remaining offers by cost and date. The generator checks that its intended winner agrees with this selector before saving the case.

Hand-authored tests verify the selector separately. Dataset tests check catalog references, scenario properties, unique winners, split coverage, and reference answers using an independent calculation. These checks help catch mistakes in the generator itself.

The case envelope separates model input from the expected answer:

| Field | Purpose | Sent to OCI as task input? |
| --- | --- | --- |
| `id` | Stable case identity | No |
| `input` | Request and offers | Yes |
| `expected_output` | Correct offer identifier | No |
| `metadata` | Scenario, seed, split and versions | No |

The model receives the natural-language rules and instructions in addition to `input`. Reference answers and scenario labels remain outside its prompt.

### 5.4 Control accidental shortcuts and development leakage

Case and offer order are shuffled. Offer IDs are neutral, and the winning offer appears in each of the six positions either 16 or 17 times. This reduces obvious positional cues.

The split contains **20 development cases** and **80 held-out evaluation cases**. Every scenario contributes two development cases and eight evaluation cases. Development cases support prompt iteration; held-out cases support assessment after those changes. Repeatedly tuning on the held-out results would weaken that separation.

The default runner selects the 80 evaluation cases. `--split all` explicitly includes both groups; it should not be described as a purely held-out result.

### 5.5 Preserve reproducibility and acknowledge limits

Generation uses seed `42` and date origin `2027-01-01`. The [manifest](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/express-order-v1.manifest.json) records source hashes, dataset hash, versions, and coverage distributions. The same source artifacts and generation configuration reproduce the dataset bytes.

This makes the test inputs reproducible. It does not make remote model outputs deterministic.

The scenario mix is balanced by design, rather than sampled from a production workload. Synthetic success therefore measures adherence to these specified scenarios. Broader claims would require representative operational data, additional cases, and an agreed release policy. The dataset is also public, so its held-out split is a project development convention rather than a private benchmark.

## 6. Executing the model-backed task

The model is called directly through the **OCI Generative AI Responses API**. The OpenAI Python SDK supplies the compatible request interface, while Oracle's authentication helper signs requests using the user's OCI configuration and the key it references.

Region, model, project, and Langfuse connection settings come from environment configuration. The implementation uses OCI IAM user-principal signing, not a Generative AI service API key. Credentials are not part of prompts, dataset files, or logged experiment metadata.

The [OCI client module](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/oci_model.py) accepts final instructions and JSON-serializable input. It contains no procurement rules. The selected task adapter builds the prompt and validates the returned answer.

Calls execute sequentially. The default pause is two seconds between invocations; `EVAL_SLEEP_SECONDS` or `--sleep-seconds` changes it. There is no sleep before the first call. Automatic SDK retries and the signing helper's automatic authentication resubmission are disabled, keeping the request count and pacing explicit.

A banner and numbered initialization logs show dataset checks, configuration, client creation, Langfuse authentication, and dataset upload. The upload occurs before inference and sends selected items one at a time, so initialization time can include many network round trips. A progress bar then tracks persisted case attempts, including failures.

## 7. Scoring correctness without hiding failures

The Express Order adapter compares the parsed `selected_offer_id` with `expected_output.expected_offer_id`. It assigns a binary correctness score, with no LLM judge.

| Status | Meaning | Correctness score |
| --- | --- | --- |
| `correct` | Valid answer matches the reference | 1 |
| `incorrect` | Valid answer differs from the reference | 0 |
| `invalid_output` | Response violates the output contract or generation is incomplete | Not assigned |
| `api_error` | Provider invocation failed | Not assigned |
| `evaluator_error` | Task parser/scorer failed unexpectedly, or scoring returned an unsupported value | Not assigned |

An offer ID that exists but is ineligible is a validly structured, incorrect selection. An unknown offer ID is invalid output. These are different failure modes and should remain distinguishable.

Two aggregate metrics are recorded:

```text
accuracy = correct answers / valid scored cases
success_rate_all_attempts = correct answers / attempted cases
```

For illustration, suppose 80 attempts produce 60 correct answers, 10 incorrect answers, 5 invalid outputs, 3 API errors, and 2 evaluator errors. Accuracy is `60 / 70`, approximately 85.7%; overall success rate is `60 / 80`, or 75%. These are hypothetical numbers, not measured results from this demo.

The summary also reports selected, attempted, valid-scored, and unattempted counts. If no output can be scored, accuracy is null. This prevents a high score over a small successful subset from obscuring widespread execution failures.

## 8. Using Langfuse in detail

Langfuse provides the experiment record around our application code. OCI performs inference, our Python task parses and scores the answer, and Langfuse receives the dataset items, execution traces, and resulting scores. The implementation is in the [tracking module](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/langfuse_tracking.py) and the [shared runner](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/evaluate.py).

### 8.1 Connect a project

The runner reads `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` from the environment, with `.env` support. It initializes a Langfuse client and checks authentication before starting model calls.

This gives early feedback for configuration errors. It also keeps provider credentials and observability credentials separate: the OCI signing identity is used for OCI calls, while Langfuse keys identify the experiment project.

Only synthetic cases selected for the run are uploaded. A one-case smoke test does not upload all 100 cases.

### 8.2 Map local cases to hosted dataset items

The mapping follows the local case envelope:

| Local content | Langfuse content |
| --- | --- |
| Request and offers in `input` | Dataset item input |
| Reference in `expected_output` | Dataset item expected output |
| Scenario, versions, split and seed | Dataset item metadata |
| Local case ID | `case_id` in item metadata |
| Task identity and dataset/rules versions | Dataset metadata |

The checked-in JSON remains the source used to initialize each experiment. The runner does not silently replace it with edited hosted data.

Dataset names combine the task's namespace, selected split, and a prefix of the source dataset hash. Item IDs are deterministic hashes of that dataset name and the local case ID. This keeps different tasks and splits separate and allows repeated synchronization of the same cases without creating a fresh item identity each time.

Uploads still happen at each initialization, even when items already exist. Stable IDs prevent identity duplication; they do not eliminate the network requests. A run limited to one case uploads that item, and a later larger run can add the remaining items to the same hosted dataset.

### 8.3 Name and execute an experiment

The user must provide an experiment name. The SDK receives that name, while each execution also has a unique run-name suffix and local run ID. This keeps repeated executions identifiable.

The SDK experiment receives the uploaded items, a task callable, and an evaluator callable. We set `max_concurrency=1`, preserving the sequential invocation and pacing policy of the local runner.

The task callable finds the corresponding local case, sends its input to OCI, parses and scores the result through the selected adapter, and saves the local record. The Langfuse evaluator converts the already-computed result into score objects. It does not make another model call or implement a second procurement algorithm.

### 8.4 Connect each score to execution evidence

The SDK traces experiment tasks. Within each task, the runner creates a generation observation named for the selected task, such as `oci-offer-selection`.

That observation records the model identifier, final instructions, task input, raw output, configured output-token limit, and returned token usage when available. The task result carries parsed output, reference output, status, score, latency, and safe error details.

This makes a failed score actionable. For example, a reviewer can distinguish an ignored delivery constraint from malformed JSON or an API connection failure. The trace helps explain what happened; the score states whether the business expectation was met.

The application does not capture authentication headers or private-key material. It records token counts, but does not implement monetary inference-cost calculation; token usage should not be presented as a verified euro cost.

### 8.5 Publish complementary scores

For Express Order, the adapter's correctness metric is `selection_correct`. The tracking layer also publishes three shared metrics:

| Score | Type | Interpretation |
| --- | --- | --- |
| `selection_correct` | Numeric 0/1 | Exact correctness, emitted only for scored answers |
| `valid_output` | Numeric 0/1 | Whether parsing produced a valid task answer |
| `execution_status` | Categorical | Correct, incorrect, invalid output, API error, or evaluator error |
| `case_success` | Numeric 0/1 | 1 only for a correct answer, 0 for every other attempt |

A scorer failure can have `valid_output=1` while receiving no correctness score: parsing worked, but evaluation did not. If parsing itself fails unexpectedly, output validity remains false.

The average of available `selection_correct` scores uses the valid-scored subset. Inspect status and attempt counts before interpreting it as overall reliability. The average of `case_success` uses every attempt and equals the local `success_rate_all_attempts`; filtering `case_success = 0` lists every KO case. Run-level aggregate scores are not published.

### 8.6 Review a run and compare changes

A useful review sequence is:

1. Open the experiment identified by the URL in the local summary.
2. Confirm its case coverage, task, model, and versions match the intended run.
3. Inspect correctness and output validity alongside execution status.
4. Open incorrect or failed items and examine their outputs and generation traces.
5. Compare a baseline and candidate on the same cases with the same evaluator definition.

Changing one condition at a time makes differences easier to interpret. Model or prompt changes can be compared while keeping the dataset and business rules fixed. If business rules change, expected answers and provenance must be reviewed and versioned as well; old labels cannot automatically remain the reference.

Aggregate improvement can hide a regression in an important case. Review individual changed outcomes, using case IDs and scenario metadata to identify which behavior changed. Scenario metadata is preserved, but the runner currently computes overall summary metrics rather than separate per-scenario aggregate reports.

### 8.7 Preserve the information needed for reproduction

Experiment metadata includes task identity/version, metric name, model, region, split, request limits, sleep settings, SDK versions, and hashes of rules, dataset, prompt, shared code, and task callback source files when available.

Rules and output instructions are maintained in the repository and assembled locally. This demo does not use Langfuse prompt management as the source of its prompts. Version and hash metadata connect an observed result back to the artifacts that produced it.

Stable inputs make comparisons meaningful, while the model's output may still vary between repeated experiments. Repeated-run analysis is a possible extension; it is not an aggregate automatically produced by this runner.

### 8.8 Flush, verify, and retain local evidence

At completion, the runner flushes the Langfuse client. It reports `submitted_unverified` when SDK execution and flush finish without a reported publication failure. Remote ingestion is asynchronous, so a separate UI or read-API check is needed to establish that the data is queryable.

Publication errors are reported separately. Local case results are written as they complete, and a summary is retained if later tracking or flush operations fail. Under `data/runs/<run-id>/`, the main artifacts are `metadata.json`, `results.jsonl`, and `summary.json`.

The `--no-langfuse` option runs OCI evaluations with local results only. This also provides a way to isolate provider behavior from observability setup while investigating a problem.

### 8.9 Start with Cloud and keep the connection configurable

The initial deployment target is Langfuse Cloud. The application configures the base URL and project keys externally, allowing the connection to point to a future self-hosted instance on OCI without rewriting task logic.

Deploying that instance or migrating historical project data is separate work. A configurable URL is useful preparation, not an implemented historical-data migration procedure.

## 9. Tools and their responsibilities

| Tool or artifact | Responsibility in this project |
| --- | --- |
| Python and Conda | Run generation, offline checks, and live experiments in the `agent-evals` environment |
| OCI Generative AI Responses API | Execute the model-backed task |
| OpenAI Python SDK | Supply the Responses request/response interface targeting OCI |
| HTTPX and `oci-genai-auth` | Provide the HTTP client and OCI IAM request signing |
| Langfuse Cloud and SDK | Store selected dataset cases, organize experiments, trace executions, and attach scores |
| JSON catalogs, dataset, and manifest | Preserve inspectable source data, reference labels, and provenance |
| pytest | Verify oracle correctness, generator coverage, runner behavior, and task reuse offline |
| tqdm and initialization logs | Show evaluation progress and initialization activity timings |
| Git and GitHub | Version the implementation, specifications, rules, and synthetic dataset |

The [dependency file](https://github.com/luigisaetta/agent-evals/blob/main/requirements.txt) records the supported client versions. The runtime configuration is illustrated by [.env.example](https://github.com/luigisaetta/agent-evals/blob/main/.env.example); actual credentials remain local.

## 10. A practical sequence for trying the demo

After creating or activating the `agent-evals` Conda environment and installing dependencies, begin with offline checks:

```sh
python -m pytest -q
./run_experiment.sh "Offline validation" --dry-run --split all
```

These verify the implementation and dataset structure without contacting OCI or Langfuse. They do not measure model accuracy.

After configuring OCI signing and the environment variables, run one development case:

```sh
./run_experiment.sh "Express Order smoke test" --split development --limit 1
```

Inspect the local summary and confirm the dataset item, experiment, and scores in Langfuse. Then run the held-out cases:

```sh
./run_experiment.sh "Express Order baseline" --split evaluation --sleep-seconds 5
```

Use the same dataset and evaluator definitions for subsequent comparisons. The [execution guide](https://github.com/luigisaetta/agent-evals/blob/main/docs/evaluation.md) explains configuration, exit codes, result files, and diagnostics.

The repository records a successful one-case OCI/Langfuse integration test before the reusable-task refactor. That refactor has been checked offline, including a different classification task and mocked Langfuse publication. These observations should not be presented as a full-dataset model benchmark.

## 11. Using this project as a starting point

The reusable part of the project handles dataset envelopes, manifest checks, provider access, pacing, logging, progress, result persistence, diagnostics, and Langfuse integration. Business-specific behavior belongs in one adapter module plus its rules and data.

The [task descriptor](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/task.py) defines four callbacks:

| Callback | What changes for another use case |
| --- | --- |
| `validate_case` | Domain input schema and reference-answer validation |
| `build_instructions` | Task instructions and required model output format |
| `parse_output` | Parsing and semantic validity of the model answer |
| `score_output` | Binary comparison with the expected business result |

The adapter also supplies display names, default data/rule paths, a dataset namespace, task version, and correctness-metric name. The [Express Order adapter](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/tasks/offer_selection.py) provides a concrete implementation.

For another task, define the success criterion first, create an appropriate reference dataset, implement the four callbacks, and select the module using `--task`. For example, if a message-priority adapter has been added as `agent_evals.tasks.message_priority`:

```sh
./run_experiment.sh "Priority baseline" --task agent_evals.tasks.message_priority
```

That module name is an adaptation example, not an additional production adapter shipped with this demo. The [cross-task tests](https://github.com/luigisaetta/agent-evals/blob/main/tests/test_task_reuse.py) demonstrate priority classification with plain text inputs and label outputs through the shared pipeline.

New local results use generic `output` and `expected_output` fields, while the summary uses `accuracy`. A different task can therefore represent its own answer without introducing procurement fields into the runner or tracking code.

The current contract supports binary correctness, local JSON datasets, natural-language rules, and OCI Responses. Fractional or multiple domain metrics, other providers, more complex interaction trajectories, and generalized synthetic generation would need explicit extensions. The [adaptation guide](https://github.com/luigisaetta/agent-evals/blob/main/docs/adapting-tasks.md) covers the concrete file contracts and result-schema migration.

## 12. Reading the evidence responsibly

The demo establishes a method for collecting evidence about a task. Its strongest claims are about explicit rules, reproducible cases, transparent scoring, observable execution, and reuse of the surrounding pipeline.

Before applying it to a production agent, expand coverage to the real input distribution, define policies for ambiguous or impossible requests, review reference labels with domain experts, and choose acceptance criteria appropriate to the business consequences. Add workflow-level tests for the agent's other responsibilities.

Those additions build on the same feedback loop: describe the expected outcome, run comparable cases, preserve failures as well as successes, and inspect the execution evidence before deciding what to change.
