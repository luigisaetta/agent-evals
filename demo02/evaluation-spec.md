# Demo02 evaluation and Langfuse publication

## Scope and organization

Evaluate the existing two-step LangGraph agent against the Demo02 synthetic
dataset and publish dataset items, experiment results, scores and one generation
observation per attempted model step to Langfuse. Keep Demo02-specific code,
documentation and its experiment launcher under `demo02/`. Do not move Demo01
files. Future demos can provide their own folder and task adapter while reusing
`agent_evals` for configuration, CLI, persistence, progress and publication.

## Shared execution contract

Extend `EvaluationTask` with an optional invoker factory and explicit source
artifacts. A factory receives the initialized client, settings, selection
rules and optional Langfuse client, and returns a callable accepting only
task input. It owns multi-call pacing and generation observations. Return the
existing Responses envelope plus optional steps, extracted request and safe
`execution_error`; no references reach this boundary. A failed pipeline remains
unscored and stops according to the existing agent graph. Preserve default
single-call execution for Demo01.

The shared evaluator handles safe execution errors without treating them as
valid answers. The Demo02 adapter validates NL inputs and reference membership,
reuses Demo01 parsing/scoring, and invokes the compiled graph. Final correctness
is exact selected-offer ID match; a valid wrong answer is scored zero. Invalid
extractions, incomplete outputs, API failures and agent internal failures are KO
but excluded from accuracy over valid scored outputs. Report overall success
across all attempts alongside that accuracy. Do not recompute expected answers.

## CLI, progress and metadata

Require an experiment name. Keep the existing banner and numbered initialization
activities. Demo02 uses a compact progress bar updating OK and KO after every
attempt, with no per-case log lines during execution. OK means correct; every
other attempted outcome is KO. Print KO IDs and statuses only after the bar
closes, and save them in the summary. Unattempted cases remain separate.

Support existing split/limit, sleep, environment, output directory, dry-run and
no-Langfuse options. Default split remains evaluation; `--split all` runs every
record. No full dataset run occurs during implementation verification.

## Dataset versions

The default dataset is `demo02-express-order-v2.json` (300 records: L0, L1 and
L2 for each source case; 240 evaluation and 60 development records). Version 1
(100 records) remains selectable with `--dataset`. The adapter accepts both
reference shapes: `{"expected_offer_id"}` (v1) and `{"expected_offer_id",
"expected_request"}` (v2). When present, `expected_request` must contain exactly
non-empty `part_id` and `delivery_location` strings and an ISO
`latest_delivery_date`; it is stored with each local result next to the
agent's `extracted_request` but is not yet scored or published as a separate
Langfuse metric. The hosted-dataset namespace is `demo02-express-order`; the
dataset hash in the hosted name distinguishes versions.

Persist model name in run metadata, every result's metadata, summary, experiment
metadata and each Langfuse generation's model field. Save both step records,
aggregate usage, extracted request and safe errors. Hash both prompts and all
Demo02 Python sources in addition to shared source hashes. Keep model access
through OCI IAM Responses; use one configured model and one paced caller across
all cases, with no additional runner sleep or automatic retries.

## Publication and verification

Use the shared deterministic dataset-item IDs and the dedicated `demo02-express-order` namespace.
Publish selection_correct, valid_output and execution_status via the existing
Langfuse evaluator. Publish two generations on success, only the attempted
generation on extraction failure. Avoid a misleading third outer generation.
Preserve local results on publication failure and report submission separately
from remotely verified persistence.

Test the compiled graph through the shared runner with mocked OCI and Langfuse:
correct, wrong, extraction failure, selection failure, continued subsequent
cases, model metadata, compact counters/KO log, source isolation, source hashes,
two-node observations, pacing across cases and publication failure. Check both
demo launchers with offline validation. Run one development case live, publishing
only that synthetic case, then inspect remotely persisted run and generations
when service access permits.
