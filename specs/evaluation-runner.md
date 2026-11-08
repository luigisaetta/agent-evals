# OCI Responses evaluation runner

## Scope

Implement a readable, sequential Python runner for the existing Express Order dataset. Keep configuration, OCI model access, evaluation, and Langfuse publication in small modules. Use Google-style docstrings. The oracle supplies reference labels during dataset generation and testing; evaluation startup does not recompute them.

## Configuration and authentication

Read `.env` without overriding existing environment variables. Use the existing names `OCI_REGION`, `OCI_MODEL`, `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`. OCI IAM signing uses `OciUserPrincipalAuth`, the key referenced by `~/.oci/config`, and profile `DEFAULT`. Allow `OCI_CONFIG_FILE` and `OCI_PROFILE` overrides. Do not use a provider API key. The OpenAI SDK's required `api_key="not-used"` is only a placeholder; the HTTP client signs requests using OCI credentials.

Configure `OCI_PROJECT_ID` for the Generative AI project required by the documented Responses endpoint. Fail before model calls when required settings are missing. Never print secrets, key material, config contents, HTTP headers, or unsanitized SDK exception messages.

Use `EVAL_SLEEP_SECONDS` (default 2) with a `--sleep-seconds` override. Require a finite, non-negative value. Run one invocation at a time, with the full configured pause before each subsequent invocation, including after failed calls. Disable automatic provider retries so no unpaced model calls are hidden. Make timeout and maximum output tokens configurable; do not assume all models support temperature or server-enforced JSON schemas.

## Execution and outputs

* CLI requires a non-blank `--experiment-name` (`--run-name` remains an alias), including for dry runs. Pass the supplied name unchanged as the Langfuse experiment name and record it in local metadata. Keep a unique run-name suffix and local run identifier so repeated executions remain distinct.
* CLI supports dataset/rules paths, split (`evaluation` by default, `development`, or `all`), positive case limit, local output directory, and disabling Langfuse.
* Provide an executable root-level `run_experiment.sh EXPERIMENT_NAME [OPTIONS...]` wrapper that runs Python in the `agent-evals` Conda environment from the repository root and forwards CLI options and exit status. Names containing spaces must be supported. Missing or blank names must fail before any service call.
* Show a `tqdm` progress bar over the selected cases for both local and Langfuse runs. Advance after every persisted attempt, including failures, preserve per-case status messages without disrupting the bar, and close the bar when execution ends or fails.
* A `--dry-run` validates dataset structure, reference ID membership, and dataset/rules hashes without network access or needing credentials. It never recomputes reference winners or reports model accuracy.
* Print numbered English initialization activities immediately, followed by `OK` and elapsed seconds on completion or `FAILED` on errors. Cover dataset checks, configuration, rules/metadata preparation, OCI signing client creation, Langfuse client/authentication/dataset setup, and uploading the selected cases. Do not print credentials. Mark the transition to evaluation explicitly.
* Each call receives only the natural-language rules, output instructions, and the case's `input`. Exclude expected output and scenario metadata.
* Require a JSON object with exactly one non-empty `selected_offer_id` referring to a supplied offer. Malformed responses, incomplete generation, and unknown IDs are invalid outputs, distinct from valid but incorrect selections.
* Record per-case expected/actual IDs, raw model text, status, optional score, usage, latency, and safe error classification. Distinguish invalid outputs from provider errors. Persist each case as JSONL immediately and write an aggregate summary; ignore generated run files in Git.
* For connection failures, inspect the exception cause chain and report safe DNS, TLS, timeout, proxy, or refused-connection categories in saved results and progress messages. Never expose raw exception text or request headers.
* Compute selection accuracy over valid scored cases and success rate over all attempts. Report denominators and status counts; no valid results means null accuracy, not a perfect or zero accuracy claim.
* Capture dataset/rules/prompt hashes, versions, SDK versions, model and region, split, sleep, timeout, token limit, and unique run identifier. Do not capture credentials or the full environment.

## Langfuse

Enable Langfuse by default for actual runs, with `--no-langfuse` for local execution. Sync only selected synthetic cases using deterministic item IDs scoped by dataset contents, split and case IDs. Run the Langfuse experiment via the SDK with `max_concurrency=1`, recording case status and exact-match scores. Trace model input/output and available token usage without credential headers. Reuse the same task code for local-only execution.

Validate Langfuse credentials before any provider calls. Flush at completion and preserve local results if publication fails. Do not equate a flush attempt with confirmed remote persistence; report submitted publication separately from verification. Provide explicit errors for dataset upload/experiment setup failures and keep final run summaries after execution.

## Verification

Use mocked OCI and Langfuse clients for tests of signing configuration, prompt isolation, output parsing, sequential pacing (including errors), exact scoring, split/limit handling, failure summaries, local persistence, and publication mapping. Verify installed SDK signatures locally. Do not execute a live model run or publish data merely as part of unit tests. An optional live smoke test requires configured project/model access and is reported separately.

## Authoritative references

* [OCI Responses API](https://docs.oracle.com/en-us/iaas/Content/generative-ai/responses-api.htm)
* [OCI IAM signing and project setup](https://docs.oracle.com/en-us/iaas/Content/generative-ai/get-started-agents.htm)
* [Oracle OCI authentication helpers](https://github.com/oracle-samples/oci-genai-auth-python)
* [Langfuse experiment SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
* [Langfuse datasets](https://langfuse.com/docs/evaluation/experiments/datasets)
