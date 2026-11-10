# Running the offer-selection evaluation

The runner invokes the selected model on OCI Generative AI through Responses (the default) or native chat using `langchain_oci`. Both Demo01 and Demo02 use the same interface selection. It authenticates using the private key referenced by your OCI config file and records results locally and, by default, in Langfuse Cloud. Expected answers are read from the dataset; the deterministic oracle is used during dataset generation and automated tests, without recomputing winners at evaluation startup. Express Order is the default task adapter. Use `--task` with another trusted module to reuse the same runner; see [the adaptation guide](adapting-tasks.md).

## Setup

```sh
conda activate agent-evals
python -m pip install -r requirements.txt
```

Configure your ignored `.env`; [.env.example](../.env.example) lists safe placeholders. Existing process environment variables take precedence over the file.

| Variable | Required/default | Purpose |
| --- | --- | --- |
| `OCI_REGION` | Required | Regional OCI inference endpoint |
| `OCI_MODEL` | Required | Supported model ID or dedicated endpoint OCID |
| `OCI_MODEL_INTERFACE` | `responses` | `responses` or `langchain_oci`, shared by both demos |
| `OCI_PROJECT_ID` | Required for `responses` | Generative AI project OCID |
| `OCI_COMPARTMENT_ID` | Required for `langchain_oci` | Compartment OCID for native chat |
| `OCI_MODEL_NAME` | Required for dedicated endpoints only | Underlying exact model ID used for compatibility checks |
| `OCI_CONFIG_FILE` | `~/.oci/config` | OCI signing configuration |
| `OCI_PROFILE` | `DEFAULT` | User-principal profile referencing your signing key |
| `OCI_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `OCI_MAX_OUTPUT_TOKENS` | `2048` | Maximum output tokens, including any model reasoning |
| `EVAL_SLEEP_SECONDS` | `2` | Full pause between consecutive invocations |
| `LANGFUSE_BASE_URL` | Required with Langfuse | Your Cloud region or self-hosted URL (self-hosted Langfuse v4.59.0 or later; see [self-hosted Langfuse](langfuse-self-hosted.md)) |
| `LANGFUSE_PUBLIC_KEY` | Required with Langfuse | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | Required with Langfuse | Langfuse project secret key |

Responses uses `OciUserPrincipalAuth` from Oracle's `oci-genai-auth` package. The SDK's `api_key="not-used"` is a placeholder, not a service API key. Native chat uses the OCI SDK's user-principal signing with the same configuration file and profile. Region and model come from the environment; there is no automatic provider/model/interface fallback. IAM permissions and model availability must allow the selected API in that region. See the [OCI setup and signing examples](https://docs.oracle.com/en-us/iaas/Content/generative-ai/get-started-agents.htm).

The project uses OpenAI SDK 2.x with HTTPX 0.28.1 to match the Oracle auth helper's HTTPX integration. Native chat uses `langchain-oci==0.4.0`; Langfuse is pinned to SDK 5.2.0. Demo01 makes one model call; Demo02 orchestrates two with LangGraph. Both share the selected transport and retain their existing prompts, parsers, scoring and pacing.

For example, select Cohere Command A for either demo:

```dotenv
OCI_MODEL_INTERFACE=langchain_oci
OCI_MODEL=cohere.command-a-03-2025
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..your-compartment
```

Use the normal demo launchers after editing `.env`. To return to Responses, set
`OCI_MODEL_INTERFACE=responses`, choose a registered Responses model, and provide
`OCI_PROJECT_ID`. Leave `OCI_MODEL_NAME` unset for on-demand models; for dedicated
endpoints set `OCI_MODEL` to the endpoint OCID and `OCI_MODEL_NAME` to its model ID.

Startup checks the exact model against the small
[verified compatibility registry](../specs/model-interfaces.md) before initializing
OCI or publishing to Langfuse. Unregistered combinations fail with a configuration
error. The registry is a supported project subset, not the entire OCI catalog;
notably, Cohere Command A Reasoning requires V2 mapping work and is not registered.
This local check does not test live permissions, regional availability or the
identity actually hosted behind a dedicated endpoint. No startup generation probe
is sent. Dataset-only `--dry-run` remains offline and does not load model settings.

Native chat disables SDK and LangChain parameter-repair retries, streaming and
caching. Output-token limits map to native `max_tokens`; no temperature is forced.
Truncated or unknown finishes are rejected, and missing token usage stays absent.
Only `langchain_oci` removes one outer Markdown code fence labelled `json` (or
unlabelled) when it encloses the entire completed response. JSON validation stays
strict; prose outside the fence, multiple blocks and other language labels are
not accepted. Changed responses retain `provider_raw_output` and
`output_normalization` in local Demo01 results or Demo02 step records. Responses
and prompts are unchanged. This formatting normalization does not correct
extracted facts or selected offers.
Run metadata records the interface, underlying model identity and relevant SDK
versions; per-case results, summaries and Langfuse generations record the interface.

This guide describes the shared runner and Demo01 defaults. For NL requests and
the two-step agent, use the dedicated
[Demo02 evaluation guide](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md)
and `./demo02/run_experiment.sh "Demo02 baseline" --split all`.

## Commands

Every invocation requires a non-blank `--experiment-name`, including dry runs. `--run-name` remains an alias. The supplied name is used unchanged as the Langfuse experiment name; the displayed run name adds a unique execution suffix to keep repeated runs distinct.

The executable Demo01 launcher selects the `agent-evals` Conda environment and forwards options to Python:

```sh
./demo01/run_experiment.sh "Express Order baseline" --split evaluation --sleep-seconds 5
./demo01/run_experiment.sh "Offline validation" --dry-run --split all
```

Quote names containing spaces. The launcher runs from the repository root, preserves the Python exit code, and accepts `--help` before a name to display usage. Direct Python commands are shown below.

The root `run_experiment.sh` remains a compatibility forwarder. The dedicated
Python entry point is `PYTHONPATH=src:. python -m demo01.evaluate`; the shared
`agent_evals.evaluate` CLI remains available. See the
[Demo01 introduction](https://github.com/luigisaetta/agent-evals/blob/main/demo01/README.md)
for setup and the scope of this starting benchmark.

Validate the complete dataset offline, without credentials or uploads:

```sh
PYTHONPATH=src python -m agent_evals.evaluate --experiment-name validation --dry-run --split all
```

Run a single development case through OCI and Langfuse:

```sh
PYTHONPATH=src python -m agent_evals.evaluate \
  --split development --limit 1 --experiment-name smoke-test
```

Run the 80 held-out evaluation cases with a five-second pause:

```sh
PYTHONPATH=src python -m agent_evals.evaluate \
  --split evaluation --sleep-seconds 5 --experiment-name baseline
```

Use `--split all` to run all 100 cases, explicitly combining development and held-out data. Use `--no-langfuse` to retain local results without contacting Langfuse. `--dataset`, `--rules`, `--env-file`, and `--output-dir` override file locations. Dataset files must have their companion `.manifest.json`; the runner rejects changed dataset or rule hashes, malformed case structure, and reference IDs absent from the supplied offers before calling any service. It does not recalculate which offer should win.

A compact Agent Evals banner introduces the Automotive Express Order demo before the first log, including during dry runs. Initialization prints numbered English activities, appending `OK` and elapsed time on completion or `FAILED` if a step raises an error. Langfuse case upload is shown separately so its duration is visible before the first model invocation. For example (illustrative timings):

```text
[1] Load dataset and verify structure and hashes ... OK (0.01s)
[2] Load environment settings ... OK (0.00s)
[3] Read rules and prepare run metadata ... OK (0.01s)
[4] Initialize OCI IAM signing client ... OK (0.10s)
[5] Initialize Langfuse client ... OK (0.02s)
[6] Verify Langfuse authentication ... OK (0.20s)
[7] Create or update Langfuse dataset ... OK (0.20s)
[8] Upload 80 selected cases to Langfuse ... OK (9.00s)
[9] Initialization complete; starting evaluation ... OK
```

Dry runs finish after dataset validation; local-only runs omit the Langfuse steps.

Calls are sequential, with no pause before the first call or after the last. The full configured pause occurs before every subsequent call, including after a failed request. Automatic provider retries are disabled; a 429 response is recorded as an API error and does not trigger hidden unpaced retries. A small signing adapter also suppresses the Oracle helper's built-in 401 resubmission, so authentication failures do not trigger an extra unpaced request. Increase the sleep setting when throttling occurs. No temperature or server-enforced JSON-schema parameter is assumed; output JSON is requested in the prompt and validated locally.

## Results and scoring

A `tqdm` progress bar shows completed attempts out of the selected case count for both local-only and Langfuse runs. It advances after each result is saved, including API errors and invalid outputs. Demo01 retains per-case status messages. `--compact-progress` instead updates OK/KO counts and logs KO IDs at the end; this is the Demo02 wrapper's default. The bar closes on completion or failure.

Each run has a unique directory under ignored `data/runs/`:

* `metadata.json`: run identifier/name, task module/name/version, metric name, result schema version, model, region, split, limits, prompt/rules/dataset/code hashes, task callback source hashes, instructions, and SDK versions. The required experiment name is recorded separately, and a unique suffix is appended to run names to avoid merging repeated experiments.
* `results.jsonl`: one record per attempted case, written immediately. Includes generic `expected_output`, parsed `output`, `output_valid`, raw output, token usage when returned, latency, execution status, and score or safe error classification. Each result's metadata includes the configured `model` and `task_name`.
* `summary.json`: result schema version, task identity, metric name, model, attempt counts, unattempted count, valid-score denominator, status counts, `accuracy`, overall success rate, OK/KO counts and KO case details, run errors, publication state, and experiment URL when available.

New runs use result schema version 2. For Express Order, the chosen ID is now `output.selected_offer_id`, and the reference is `expected_output.expected_offer_id`. `accuracy` replaces `selection_accuracy` in summaries. Older run files remain unchanged; see [the migration table](adapting-tasks.md#result-schema-version-2).

`correct` and `incorrect` are valid selections scored 1 and 0 respectively. `invalid_output` includes malformed JSON, extra or duplicate output fields, unknown offer IDs, and incomplete responses. `api_error` indicates invocation failure, recording safe exception classes, HTTP status, and a root-cause category without raw SDK exception text. Connection failures show categories such as `DNS resolution failed` or `Request timed out` alongside the progress bar. Invalid outputs and API errors have no selection score and cannot count as successes.

Accuracy is correct answers divided by valid scored cases. Overall success rate is correct answers divided by all attempted cases. Always inspect failure and unattempted counts alongside these rates. Accuracy is null if there are no valid scored outputs. Unexpected task parser/scorer errors use `evaluator_error`, have no correctness score, and are counted separately from model and API failures. No experiment-level pass threshold is currently defined.

Exit codes: 0 means the run completed (including valid but incorrect answers); 1 means setup, incomplete experiment, or publication failure; 2 means at least one invalid output, evaluator error, or API error occurred. A dry run produces no model accuracy or experiment records.

Multi-step adapters also distinguish `agent_error` for internal pipeline failures;
these are KO, unscored, and produce exit code 2. Demo02 saves its extracted
request and attempted-step records alongside the common result fields.

## Langfuse behavior

The runner authenticates to Langfuse and uploads only the selected synthetic cases before inference. Dataset names are scoped by source dataset hash and split, and item IDs are deterministic, allowing safe repeated uploads. With a case limit, only that subset is uploaded; subsequent larger runs can add the remaining cases. Expected answers and scenario metadata stay outside the OCI model prompt.

The SDK experiment runs with `max_concurrency=1`, creates generation traces, and attaches `valid_output`, `execution_status`, `case_success` (0 for every KO case), the task's correctness metric for scored outputs, and any applicable task-specific extra scores. Each local result records the Langfuse `trace_id`. Express Order keeps the `selection_correct` metric and existing dataset namespace. Langfuse receives the score computed by the selected adapter, with no domain-specific scoring code in the tracking module. This uses the documented [Langfuse SDK experiment workflow](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk).

Local result files remain available when tracing/publication fails after execution begins. `submitted_unverified` means SDK execution and flush completed; asynchronous ingestion has not been independently confirmed. Inspect the experiment URL in Langfuse to verify persistence. A reported SDK/publication failure gives `failed`, never successful publication.

## Verification

```sh
python -m pytest -q
```

Unit tests use mocked clients and make no OCI or Langfuse calls. A live smoke run is a separate integration check; its result does not establish accuracy over the full dataset.

On 2026-11-08, all 56 automated tests passed, including the shared pipeline's use with an independent classification fixture and mocked Langfuse publication. Before the reusable-task refactor, a one-case development smoke test successfully invoked OCI Responses using IAM signing and selected the expected offer. Its dataset item, experiment, and scores (`valid_output=1`, `selection_correct=1`, `execution_status=correct`) were independently confirmed through the Langfuse read API. The refactor has been verified offline; no new live run or full-dataset accuracy measurement is claimed for it.

On 2026-11-09, all 89 tests passed, including Demo02's shared-runner integration.
A live one-case Demo02 development run produced the expected selection. Langfuse
read API checks independently confirmed its experiment item, model metadata,
three scores and two generation observations. This is an integration smoke test,
not a full-dataset accuracy measurement.
