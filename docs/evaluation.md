# Running the offer-selection evaluation

The runner invokes the selected model on OCI Generative AI through the Responses API. It authenticates using the private key referenced by your OCI config file and records results locally and, by default, in Langfuse Cloud. The deterministic oracle is used only to validate dataset labels before the experiment.

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
| `OCI_PROJECT_ID` | Required | Generative AI project OCID |
| `OCI_CONFIG_FILE` | `~/.oci/config` | OCI signing configuration |
| `OCI_PROFILE` | `DEFAULT` | User-principal profile referencing your signing key |
| `OCI_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `OCI_MAX_OUTPUT_TOKENS` | `2048` | Maximum output tokens, including any model reasoning |
| `EVAL_SLEEP_SECONDS` | `2` | Full pause between consecutive invocations |
| `LANGFUSE_BASE_URL` | Required with Langfuse | Your Cloud region or self-hosted URL |
| `LANGFUSE_PUBLIC_KEY` | Required with Langfuse | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | Required with Langfuse | Langfuse project secret key |

OCI access uses `OciUserPrincipalAuth` from Oracle's `oci-genai-auth` package. The SDK's `api_key="not-used"` is a placeholder, not a service API key. Region and model come from the environment; there is no automatic provider/model fallback. The project and IAM permissions must allow Responses calls for that model in that region. See the [OCI setup and signing examples](https://docs.oracle.com/en-us/iaas/Content/generative-ai/get-started-agents.htm).

The project uses OpenAI SDK 2.x with HTTPX 0.28.1 to match the Oracle auth helper's HTTPX integration. Langfuse is pinned to SDK 5.2.0, whose experiment API was checked against the installed package. No LangChain or additional agent framework is required.

## Commands

Every invocation requires a non-blank `--experiment-name`, including dry runs. `--run-name` remains an alias. The supplied name is used unchanged as the Langfuse experiment name; the displayed run name adds a unique execution suffix to keep repeated runs distinct.

The executable launcher in the repository root selects the `agent-evals` Conda environment and forwards options to Python:

```sh
./run_experiment.sh "Express Order baseline" --split evaluation --sleep-seconds 5
./run_experiment.sh "Offline validation" --dry-run --split all
```

Quote names containing spaces. The launcher runs from the repository root, preserves the Python exit code, and accepts `--help` before a name to display usage. Direct Python commands are shown below.

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

Use `--split all` to run all 100 cases, explicitly combining development and held-out data. Use `--no-langfuse` to retain local results without contacting Langfuse. `--dataset`, `--rules`, `--env-file`, and `--output-dir` override file locations. Dataset files must have their companion `.manifest.json`; the runner rejects changed dataset or rule hashes and inconsistent labels before calling any service.

Calls are sequential, with no pause before the first call or after the last. The full configured pause occurs before every subsequent call, including after a failed request. Automatic provider retries are disabled; a 429 response is recorded as an API error and does not trigger hidden unpaced retries. A small signing adapter also suppresses the Oracle helper's built-in 401 resubmission, so authentication failures do not trigger an extra unpaced request. Increase the sleep setting when throttling occurs. No temperature or server-enforced JSON-schema parameter is assumed; output JSON is requested in the prompt and validated locally.

## Results and scoring

A `tqdm` progress bar shows completed attempts out of the selected case count for both local-only and Langfuse runs. It advances after each result is saved, including API errors and invalid outputs. Per-case status messages remain visible, and the bar closes on completion or failure.

Each run has a unique directory under ignored `data/runs/`:

* `metadata.json`: run identifier/name, model, region, split, limits, prompt/rules/dataset/code hashes, instructions, and SDK versions. The required experiment name is recorded separately, and a unique suffix is appended to run names to avoid merging repeated experiments.
* `results.jsonl`: one record per attempted case, written immediately. Includes expected and selected IDs, raw output, token usage when returned, latency, execution status, and score or safe error classification.
* `summary.json`: attempt counts, unattempted count, valid-score denominator, status counts, metrics, run errors, publication state, and experiment URL when available.

`correct` and `incorrect` are valid selections scored 1 and 0 respectively. `invalid_output` includes malformed JSON, extra or duplicate output fields, unknown offer IDs, and incomplete responses. `api_error` indicates invocation failure, recording only the exception class and HTTP status to avoid leaking credentials through SDK exception text. Invalid outputs and API errors have no selection score and cannot count as successes.

Selection accuracy is correct selections divided by valid scored cases. Overall success rate is correct selections divided by all attempted cases. Always inspect failure and unattempted counts alongside these rates. Accuracy is null if there are no valid outputs. No experiment-level pass threshold is currently defined.

Exit codes: 0 means the run completed (including valid but incorrect selections); 1 means setup, incomplete experiment, or publication failure; 2 means at least one invalid output or API error occurred. A dry run produces no model accuracy or experiment records.

## Langfuse behavior

The runner authenticates to Langfuse and uploads only the selected synthetic cases before inference. Dataset names are scoped by source dataset hash and split, and item IDs are deterministic, allowing safe repeated uploads. With a case limit, only that subset is uploaded; subsequent larger runs can add the remaining cases. Expected answers and scenario metadata stay outside the OCI model prompt.

The SDK experiment runs with `max_concurrency=1`, creates generation traces, and attaches `valid_output`, `execution_status`, and (for valid outputs) `selection_correct` scores. This uses the documented [Langfuse SDK experiment workflow](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk).

Local result files remain available when tracing/publication fails after execution begins. `submitted_unverified` means SDK execution and flush completed; asynchronous ingestion has not been independently confirmed. Inspect the experiment URL in Langfuse to verify persistence. A reported SDK/publication failure gives `failed`, never successful publication.

## Verification

```sh
python -m pytest -q
```

Unit tests use mocked clients and make no OCI or Langfuse calls. A live smoke run is a separate integration check; its result does not establish accuracy over the full dataset.

On 2026-11-08, all 47 automated tests passed. After correcting the local environment configuration, a one-case development smoke test successfully invoked OCI Responses using IAM signing and selected the expected offer. The hosted dataset item, experiment, and scores (`valid_output=1`, `selection_correct=1`, `execution_status=correct`) were independently confirmed through the Langfuse read API after asynchronous ingestion. The earlier HTTP 404 was due to the previous configuration. This verifies the integration for one development case; the full dataset has not been executed.
