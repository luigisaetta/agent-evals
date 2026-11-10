# Shared OCI model interfaces

## Problem and scope

Demo01 and Demo02 currently share a Responses-only transport. Add an explicit
`OCI_MODEL_INTERFACE=responses|langchain_oci` selector, defaulting to `responses`,
so both demos can also evaluate OCI chat models such as Cohere. This specification
supersedes Responses-only transport requirements in the existing demo and runner
specifications; business prompts, datasets, scores and graph behavior stay intact.

## Design and assumptions

Keep dispatch and compatibility checks in the existing shared model module and
isolate LangChain-specific code in one adapter. Preserve the public
`create_client`/`invoke_model` boundary and context-managed client lifetime. Both
backends return raw text, normalized completion status, provider response ID when
available, and available usage in the existing envelope. Do not fabricate IDs or
token counts. Retain strict application parsing; do not add JSON repair, tools,
structured-output wrappers, fallback models or fallback interfaces.

Use the existing OCI user-principal profile and credential file. Responses needs
`OCI_PROJECT_ID`; native chat needs `OCI_COMPARTMENT_ID`. A dedicated endpoint also
needs `OCI_MODEL_NAME` identifying the underlying model for compatibility validation. Validate
the selected exact model against a small documented compatibility registry before
client initialization or Langfuse publication. Unknown combinations fail closed
with actionable configuration errors. Local validation cannot prove regional
availability, permissions or live endpoint access; no implicit generation probe
is allowed. The offline dataset-only `--dry-run` remains unchanged.

### Initial compatibility registry (2026-11-10)

This is the project's verified integration subset, not the complete OCI catalog.
The registry lives in `agent_evals.oci_model.MODEL_INTERFACES`; extending it needs
authoritative API/provider evidence and offline request-mapping tests. Regions,
retirement dates and tenancy access must also be checked when selecting a model;
the local registry does not claim live regional availability.

| Exact model ID | Interface | Evidence |
| --- | --- | --- |
| `openai.gpt-oss-20b`, `openai.gpt-oss-120b` | `responses` | Oracle supported agentic models; existing demo experiments |
| `openai.gpt-6.1-terra` | `responses` | Recorded repository experiments in `specs/demo02-extraction-difficulty.md`; no claim of public catalog availability |
| `google.gemini-2.5-pro`, `google.gemini-2.5-flash`, `google.gemini-2.5-flash-lite` | `responses` | Oracle supported agentic models |
| `cohere.command-a-03-2025` | `langchain_oci` | Oracle Command A model page and installed Cohere provider |
| `meta.llama-4-scout-17b-16e-instruct` | `langchain_oci` | Oracle LangChain setup example and installed Meta provider |
| `meta.llama-3.3-70b-instruct` | `langchain_oci` | Oracle Llama 3.3 model page and installed Meta provider; same native generic-chat mapping tested offline |

Cohere Command A Reasoning is deliberately not registered: Oracle requires Chat
V2, but the installed 0.4.0 provider automatically selects V2 only for vision
models/content. Supporting it requires a separate verified mapping change.
Other unregistered models fail closed; they are not necessarily unsupported by OCI.

### Implementation decisions

Keep the existing `PacedResponses` name as a compatibility wrapper for either
backend. A small `ChatOCIGenAI` subclass overrides the pinned private
`_chat_with_param_retry` hook to issue exactly one unchanged native request;
both client and per-call OCI retry strategies are `NoneRetryStrategy`. Recheck
this hook when upgrading `langchain-oci`. Disable caching, streaming and response
content-block conversion. LangChain `generate` preserves the native request ID
in message response metadata; never use its locally generated message ID as an
OCI response ID. Aggregate Demo02 usage only when every attempted step supplies
that count. No missing usage is presented as a measured zero.

Pin and inspect `langchain-oci` in the `agent-evals` Conda environment. Use native
OCI chat, with SDK retries disabled and no LangChain parameter-repair retries.
Keep configured timeout and output-token limits explicit. Preserve existing
pacing ownership: the runner paces Demo01; Demo02 paces each actual graph call.
Record the selected interface and relevant installed SDK versions with runs,
per-case results, summaries and Langfuse generation/experiment metadata. Adapt
safe error classification for OCI SDK exceptions without exposing their text.

## Acceptance criteria and verification

* Both demos use the configured backend through the same shared boundary.
* Existing valid Responses configuration remains usable without new variables.
* Missing backend-specific settings, unknown interfaces and unsupported model
  combinations fail before requests or publication; no automatic fallback occurs.
* LangChain messages contain only the existing instructions and JSON task input.
* Completed, truncated, blocked and unknown finish reasons are distinguished;
  only explicitly successful completion may reach normal output parsing.
* Extraction failures prevent selection; both successful graph calls use one
  selected backend/model; no unpaced retries occur, including parameter errors.
* Mocked tests cover configuration, compatibility, both transports, normalization,
  errors, pacing, graph execution and publication metadata. Run the full offline
  suite and available lint checks. Do not call OCI or publish Langfuse data as
  part of verification; document that live integration is unverified.

## Authoritative references

* [OCI Responses](https://docs.oracle.com/en-us/iaas/Content/generative-ai/responses-api.htm)
* [Supported agentic models](https://docs.oracle.com/en-us/iaas/Content/generative-ai/agentic-regions.htm)
* [Oracle LangChain setup](https://docs.oracle.com/en-us/iaas/Content/generative-ai/setup-oci-langchain.htm)
* [Oracle integration source](https://github.com/oracle/langchain-oracle)
* [Cohere Command A](https://docs.oracle.com/en-us/iaas/Content/generative-ai/cohere-command-a-03-2025.htm)
* [Cohere Command A Reasoning and V2](https://docs.oracle.com/en-us/iaas/Content/generative-ai/cohere-command-a-reasoning-08-2025.htm)
* [Meta Llama 3.3 (70B)](https://docs.oracle.com/en-us/iaas/Content/generative-ai/meta-llama-3-3-70b.htm)

## Verification record (2026-11-10)

Installed `langchain-oci==0.4.0` from `requirements.txt` in `agent-evals`;
`pip check` reports no broken requirements. Existing OpenAI, OCI and LangGraph
versions were retained. The full offline suite passes 150 tests, including real
LangChain Cohere/Meta mappings with mocked OCI transport, both demo evaluation
runners and mocked Langfuse generation metadata. Ruff correctness checks
(`E4`, `E7`, `E9`, `F`) cover all changed Python files; the new adapter and tests
are formatted with Ruff. Both launcher dry runs pass (100 Demo01 and 300 Demo02
records). The existing ignored `.env` passes local model/interface validation.
No live model calls or Langfuse uploads were performed. Native-chat access,
actual model output quality and remote trace persistence remain unverified.
