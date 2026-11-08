# Public demo documentation

## Objective and scope

Prepare the main English README for a public repository audience. Lead with the project's objective: explore systematic evaluation of an agent's performance through a concrete, reproducible example. Present the evaluation method, questions it helps investigate, tools and reusable pipeline before introducing Automotive Express Order as the initial demonstration. Preserve a clear distinction between evaluating one task and validating an entire agent. Describe implemented behavior without promising unimplemented features or changing publication state.

## Acceptance criteria

* Open with the general evaluation objective and learning outcomes. Introduce the 100-case, six-offer dataset as supporting evidence for the concrete example, rather than the project's identity.
* Explain performance in terms of the measured correctness and execution outcomes; distinguish recorded latency/token usage from unimplemented cost calculations or comprehensive performance benchmarks.
* Explain business rules, deterministic reference labels, held-out cases, and failure accounting.
* Distinguish offline software tests, dataset validation, and live OCI evaluations.
* Describe the implemented tools and workflow, including Langfuse datasets, traces, scores, and experiment comparison.
* Provide a runnable quick start with credential-free checks before explicitly invoking OCI and Langfuse.
* Report verified smoke-test scope without presenting one successful case as a benchmark result.
* Link detailed setup, specifications, source code, and dataset documentation; include no secrets, private project IDs, local machine paths, or account-specific experiment links.

## Verification

Review the README against CLI arguments, dependency declarations, dataset metadata, and recorded integration evidence. Check relative links and Markdown fences. This documentation-only change does not require new unit tests or live model calls.

## Explanatory guide

Add `docs/evals-for-agentic-solutions.md` as a structured English guide covering the importance of agent evaluations, the demo's task-level objective, implementation steps, deterministic synthetic generation and reference answers, OCI and other tools, detailed Langfuse dataset/experiment/trace/score usage, and adaptation to another task. Explain metric denominators, failure categories, scope limits, and the difference between implemented behavior and future extensions. Use GitHub repository URLs for project references, link the guide from the README, and verify claims against source code and the dataset manifest.
