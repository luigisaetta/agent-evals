# Public demo documentation

## Objective and scope

Prepare the main English README for a public repository audience. Explain the Automotive Express Order problem, demo objectives, exact-match evaluation design, OCI Responses authentication, and Langfuse's role. Present the existing implementation without publishing the repository or promising unimplemented features.

## Acceptance criteria

* Open with a clear demo proposition and the 100-case, six-offer dataset.
* Explain business rules, deterministic reference labels, held-out cases, and failure accounting.
* Distinguish offline software tests, dataset validation, and live OCI evaluations.
* Describe the implemented tools and workflow, including Langfuse datasets, traces, scores, and experiment comparison.
* Provide a runnable quick start with credential-free checks before explicitly invoking OCI and Langfuse.
* Report verified smoke-test scope without presenting one successful case as a benchmark result.
* Link detailed setup, specifications, source code, and dataset documentation; include no secrets, private project IDs, local machine paths, or account-specific experiment links.

## Verification

Review the README against CLI arguments, dependency declarations, dataset metadata, and recorded integration evidence. Check relative links and Markdown fences. This documentation-only change does not require new unit tests or live model calls.
