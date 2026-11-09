# Demo02: two-step Express Order agent

## Objective and input/output contract

Implement a local LangGraph agent with two sequential model-backed steps. Its input is the natural-language request from Demo02 plus that record's six structured JSON offers. Offers are provided by the caller; the agent does not invent or retrieve them. On success, return exactly `{"selected_offer_id": "..."}`, matching Demo01.

Use the existing `.env` configuration and OCI user-principal signing. Both steps call OCI Generative AI Responses with `OCI_MODEL`; do not introduce a provider API key, a second model, local deterministic extraction, or deterministic offer ranking.

## Graph and reuse

`START -> extract_request -> select_offer -> END`

After extraction, a conditional edge routes failures directly to `END`. Successful extraction is the only route to selection. A successful invocation makes exactly two model calls, without automatic repair/retry loops.

1. `extract_request`: send only the NL request and extraction instructions to the model. Parse exactly `part_id`, `delivery_location`, and `latest_delivery_date`. Require non-empty strings and a real ISO calendar date. Reject extra/missing/duplicate fields, invalid JSON, null values, or incomplete generation. Missing/ambiguous request facts must not be invented. Return the exclusive deadline: keep exclusive wording, and convert inclusive and relative wording as defined in `specs/demo02-extraction-difficulty.md`. Normalize part identifiers to `PART-NNN`.
2. `select_offer`: combine the validated extracted request with unchanged offers. Reuse Demo01's prompt builder, input validation and response parser through `agent_evals.tasks.offer_selection`, and reuse `agent_evals.oci_model` transport. Make a second model call and validate the selected identifier against the supplied offers.

Extract a public `validate_input` helper from Demo01's case validator so both demos can validate request/offers without constructing a fake expected answer. Preserve the existing case validation and scoring behavior.

## Errors and state

Validate the original input and all six offers before the first model call. Keep offers unchanged and never pass expected outputs, scenario metadata or source structured requests to the agent.

Graph state records the extracted request, final output, per-step response text/ID/usage/latency/status, and safe errors. Distinguish API errors, invalid model output and internal step errors. No error may produce a fabricated successful output. The public agent method returns the final output only or raises a stage-specific `AgentExecutionError` with safe diagnostics and step records. Shape validation does not prove semantic extraction correctness; end-to-end evals are subsequent work.

## Files, execution and pacing

Keep implementation under root `demo02/`: package, graph/agent, request/input validation, a thin Responses caller, extraction instructions, CLI and README. Use Google-style docstrings and existing settings. Add LangGraph as the only new direct framework dependency.

The Responses caller sleeps for the configured `EVAL_SLEEP_SECONDS` between actual requests, including the two nodes and successive agent calls sharing that caller. Never sleep before the first call. Keep SDK and auth retries disabled through the shared client.

Provide a CLI selecting a unique `--case-id` from the Demo02 dataset, with configurable dataset, rules, `.env` and sleep. Ignore references and print the successful output as JSON. Optionally write graph details locally for review. No full-dataset evaluation or automatic Langfuse upload is part of this change; preserve a clean callable boundary for future integration.

## Verification

Run the compiled LangGraph offline with mocked Responses calls. Verify two-call order, correct stage payloads, reuse of the Demo01 prompt/parser, unchanged offers, exact output contract, pacing, and no reference leakage. Cover invalid inputs, malformed/incomplete/missing-field extraction, invalid dates, extraction API errors, selection API errors, and unknown selected IDs. Every extraction failure must prevent the second invocation. Keep existing tests passing. Document any live smoke test separately; unit tests must make no network calls.
