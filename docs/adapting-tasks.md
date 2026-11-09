# Adapting the runner to another task

The shared pipeline handles OCI IAM authentication and Responses requests, pacing, initialization logs, progress, local results, error classification, and Langfuse datasets/experiments. A new use case requires three task artifacts:

1. A Python adapter module exporting `TASK`.
2. A natural-language rules file.
3. A JSON dataset and companion provenance manifest.

Synthetic generation and reference-answer creation remain task-specific authoring activities. The runner never computes the expected answer at startup.

## Where the boundary lives

| Component | Responsibility | Changes for a new task? |
| --- | --- | --- |
| `task.py` | Small descriptor and module loader | No |
| `dataset.py` | Case envelope, splits, versions, hashes | No |
| `evaluate.py` | Sequential execution, result files, metrics and CLI | No |
| `oci_model.py` | OCI signing and Responses transport | No |
| `langfuse_tracking.py` | Dataset synchronization, experiment and score mapping | No |
| `console.py`, `errors.py`, `config.py` | Shared runtime utilities | No |
| `tasks/offer_selection.py` | Express Order prompt, validation, parsing and scoring | Replace with your adapter |
| Rules, dataset, optional generator/oracle | Business rules and reference examples | Supply your own |

The [Express Order adapter](../src/agent_evals/tasks/offer_selection.py) is the default. The [classification test fixture](../tests/test_task_reuse.py) demonstrates a different task with plain text inputs, priority-label outputs, and another metric through the same pipeline, including the mocked Langfuse path.

## 1. Implement one adapter module

Implement four functions and instantiate [EvaluationTask](../src/agent_evals/task.py):

| Callback | Contract |
| --- | --- |
| `validate_case(case)` | Validate domain `input` and `expected_output`. Raise `ValueError` for bad data. Do not recalculate reference labels. |
| `build_instructions(rules)` | Return final instructions, including the required output format. The model sees these instructions and the case input only. |
| `parse_output(raw_output, task_input)` | Return a JSON-serializable answer. Raise `ValueError` for invalid model output. |
| `score_output(output, expected_output)` | Return binary correctness: 0 or 1. Other values or unexpected callback exceptions are reported as `evaluator_error`. |

Write Google-style docstrings and keep domain logic in these functions. Example descriptor, after defining the four functions in your module:

```python
from pathlib import Path
from agent_evals.task import EvaluationTask

TASK = EvaluationTask(
    name="message-priority",
    title="Message Priority Classification",
    default_dataset=Path("data/datasets/priorities-v1.json"),
    default_rules=Path("rules/priorities.md"),
    rules_manifest_key="rules/priorities.md",
    dataset_namespace="message-priority-v1",
    metric_name="priority_correct",
    validate_case=validate_case,
    build_instructions=build_instructions,
    parse_output=parse_output,
    score_output=score_output,
    version="1.0",
)
```

Paths are relative to the repository root unless absolute. The dataset namespace separates hosted data from other tasks; the metric name is used for correctness scores in Langfuse. Do not use the reserved metric names `valid_output` or `execution_status`.

## 2. Supply rules, cases and a manifest

The generic case envelope is unchanged; domain fields are unrestricted JSON values validated by your adapter. For example, a text input does not require an `offers` array:

```json
[
  {
    "id": "PRIORITY-001",
    "input": "Production has stopped",
    "expected_output": {"label": "urgent"},
    "metadata": {
      "split": "evaluation",
      "dataset_version": "1.0",
      "rules_version": "1.0"
    }
  }
]
```

Each case has exactly `id`, `input`, `expected_output`, and `metadata`. IDs must be unique non-empty strings. Metadata may include scenario information, but must declare `split` (`development` or `evaluation`) and versions matching the manifest.

Place `priorities-v1.manifest.json` beside `priorities-v1.json`:

```json
{
  "dataset_version": "1.0",
  "rules_version": "1.0",
  "dataset_sha256": "<SHA-256 of the dataset file bytes>",
  "source_sha256": {
    "rules/priorities.md": "<SHA-256 of the rules file bytes>"
  }
}
```

Generate real hashes for the final file contents using `hashlib.sha256(path.read_bytes()).hexdigest()`. The rule-source key must match `TASK.rules_manifest_key`. Keep development and evaluation cases separate when tuning the task's prompt or rules.

## 3. Select the adapter

If the module is `agent_evals.tasks.message_priority`, validate it without credentials:

```sh
./run_experiment.sh "Priority validation" \
  --task agent_evals.tasks.message_priority --dry-run --split all
```

Run the same pipeline with OCI and Langfuse:

```sh
./run_experiment.sh "Priority baseline" \
  --task agent_evals.tasks.message_priority --sleep-seconds 5
```

Use `--dataset` and `--rules` to override the adapter defaults. Modules outside this package work too when importable on `PYTHONPATH`. Selecting a module imports and executes its Python code; use trusted project modules.

Existing Express Order commands continue to use `agent_evals.tasks.offer_selection` by default. No changes to `.env`, the shell wrapper, OCI transport, or Langfuse code are needed when switching tasks, unless the provider configuration itself needs to change.

## Result schema version 2

New local runs use a domain-independent format:

```json
{
  "case_id": "PRIORITY-001",
  "expected_output": {"label": "urgent"},
  "output": {"label": "urgent"},
  "output_valid": true,
  "status": "correct",
  "score": 1
}
```

Actual records also contain metadata, raw text, usage, latency and errors. A parsed answer may be valid even when its scorer fails; `evaluator_error` makes this distinction explicit. API errors, invalid output, and evaluator errors have no correctness score.

| Before | Version 2 |
| --- | --- |
| `result.selected_offer_id` | `result.output.selected_offer_id` for Express Order |
| `result.expected_offer_id` | `result.expected_output.expected_offer_id` for Express Order |
| `summary.selection_accuracy` | `summary.accuracy` |

Summaries and run metadata include `result_schema_version`, task identity/version, and metric name. Model/rule/dataset versions and hashes are recorded, along with task callback source hashes when source files are available. Older run artifacts remain unchanged and need the previous field paths when analyzed.

Langfuse retains `selection_correct` for Express Order. Another task supplies its own correctness metric; all tasks share `valid_output` and `execution_status`. Hosted Express Order dataset names and stable item IDs retain their existing namespace.

This initial reusable contract supports **binary correctness**, JSON datasets, and rules-based prompts on OCI Responses. Fractional scores, multiple domain metrics, alternative providers, and generalized dataset generation require explicit future extensions.

## Organizing multiple demos

Keep the original Demo01 files in their existing locations. Each additional demo
gets a dedicated top-level package and launcher, following
[Demo02](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md):

```text
src/agent_evals/          Shared configuration, transport, runner and publication
demo02/                  Agent, prompts, adapter, CLI, specs and README
  evaluation.py          Exports this demo's TASK
  evaluate.py            Small wrapper selecting TASK and compact progress
  run_experiment.sh      Conda launcher with a required experiment name
demo03/                  Future demo, following the same convention
data/datasets/           Versioned datasets and manifests
data/runs/               Ignored results with task/model identity
```

New adapters use distinct task names and Langfuse dataset namespaces. Reuse the
shared CLI rather than copying its startup, dataset upload, scoring or result
storage code. A new launcher adds both the root and `src` to `PYTHONPATH`; see
[the Demo02 launcher](https://github.com/luigisaetta/agent-evals/blob/main/demo02/run_experiment.sh).
The root launcher continues to select Demo01 by default.

### Multi-step agent execution

For one-call tasks, the original four callbacks remain sufficient. A multi-step
adapter can additionally supply `create_invoker` and `source_files` in its
`EvaluationTask`. The
[Demo02 adapter](https://github.com/luigisaetta/agent-evals/blob/main/demo02/evaluation.py)
is a concrete example.

`create_invoker(*, client, settings, rules, tracking)` is called once after
service initialization. It builds the agent and returns `invoke(task_input)`.
Only task input reaches this callable; expected outputs stay in the evaluator.
The callable owns pacing between all actual model calls, including across
cases, and creates any per-node Langfuse observations. The shared runner disables
its own pause and outer generation for such adapters to avoid double delays or
misrepresenting a multi-call pipeline as a single generation.

Return `raw_output`, `response_status`, `response_id`, and `usage`, as with the
shared Responses transport. Additional JSON-compatible fields such as `steps`
and `extracted_request` are preserved. An optional safe `execution_error`
contains `stage` and `kind`; `api_error` and `invalid_output` retain those
statuses, while other pipeline failure kinds become `agent_error`. Such results
are unscored. Unexpected parser/scorer failures remain `evaluator_error`.

Optional `publication_errors` contains safe exception class names for tracing
failures. Preserve successful agent results and let the shared runner mark
publication as failed. Do not copy raw SDK exception messages into artifacts.

`source_files` lists repository-relative implementation and prompt paths for
hashing in `metadata.json`; include all files involved in execution and both
prompts. Each result's metadata and the summary record `model`. The experiment
metadata and generation model fields record it as well.

Use `--compact-progress` to show live OK/KO counts and print only KO case IDs
after execution. Demo02 enables it through its wrapper; Demo01 retains its
existing default console behavior. Shared summary files contain `ok_count`,
`ko_count`, and `ko_cases` for either display mode. OK is exact correctness;
all other attempted statuses are KO, with unattempted cases separate.
