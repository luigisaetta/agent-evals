# Using a self-hosted Langfuse instance

The experiments in this project have been run against Langfuse Cloud. This note explains what is needed to point them at a self-hosted Langfuse instance instead, for example one deployed on OCI. It is based on the Langfuse documentation as of 2026-11-09. Running this project against a self-hosted instance has not been verified yet.

## Langfuse features used by this project

| Feature | Where it is used | Self-hosted edition |
| --- | --- | --- |
| Public API authentication (`auth_check`) | Startup check of the configured keys | Open source (MIT) |
| Datasets and dataset items with deterministic IDs | Upload of the selected cases | Open source (MIT) |
| Experiments through the SDK (`run_experiment` with evaluators) | Every evaluation run | Open source (MIT) |
| Experiments in the UI | The `experiment_url` printed in the summary | Open source (MIT) |
| Tracing with generation observations, token usage, level and status message | One generation per Demo01 case; two per Demo02 case (`demo02-extract_request`, `demo02-select_offer`) | Open source (MIT) |
| Custom numeric and categorical scores | `valid_output`, `execution_status`, `case_success`, the task metric and task-specific extra scores such as `extraction_correct` | Open source (MIT) |
| `get_current_trace_id` | `trace_id` stored in each local result | Client-side SDK call |

Langfuse states that all core features are available in the open-source self-hosted edition without limits. The features that need an Enterprise license key, such as project-level RBAC, data retention policies, audit logs, server-side data masking and SCIM, are not used here.

## Server version requirement

`requirements.txt` pins `langfuse==5.2.0`. Python SDK v5 requires Langfuse Cloud or **self-hosted Langfuse v4.59.0 or later**, and Python 3.11 or later; self-hosted v3 servers are not supported. SDK v5 records experiments as OpenTelemetry spans and sends scores in batches to `POST /api/public/scores`, so an older server cannot receive them.

* With a self-hosted v4.59.0 or later server, no code change is expected.
* With a self-hosted v3 server, either upgrade the server to v4 (Langfuse recommends upgrading the server before the SDK) or move this project to Python SDK v4, which supports self-hosted v3 from 3.63.0. The SDK v4 option is not implemented: `src/agent_evals/langfuse_tracking.py` and the result checks in `src/agent_evals/evaluate.py` would need to be reviewed and tested against that SDK.

Self-hosted Langfuse v4 needs ClickHouse 25.12 or later, PostgreSQL 15 or later (16 recommended), Redis 7.0 or later (7.2 recommended), and blob storage. Upgrading an existing v3 deployment also requires a ClickHouse upgrade and a data-model migration; follow the Langfuse upgrade guide.

## Configuration

Only the connection settings change. In `.env`, set:

| Variable | Value |
| --- | --- |
| `LANGFUSE_BASE_URL` | The URL of the self-hosted instance, for example `https://langfuse.example.internal` |
| `LANGFUSE_PUBLIC_KEY` | The public key of a project created on that instance |
| `LANGFUSE_SECRET_KEY` | The secret key of the same project |

Keys are per project and per instance: Cloud keys do not work on a self-hosted instance. The machine that runs the experiments must reach the instance over HTTPS, and the startup authentication check fails if it cannot.

## Verifying a self-hosted instance

Before relying on the instance, run the same checks used with Cloud:

1. Run offline validation, which does not contact Langfuse:

   ```sh
   ./demo02/run_experiment.sh "Demo02 validation" --dry-run --split all
   ```

2. Run one development case with Langfuse enabled:

   ```sh
   ./demo02/run_experiment.sh "Self-hosted smoke test" --split development --limit 1
   ```

3. Open the printed experiment URL. Check that the dataset item, the experiment, both generation observations and all scores (including `case_success` and `extraction_correct`) are present.
4. Open the experiment comparison view with a second run of the same case. The Langfuse pricing page lists experiments in the UI for the open-source edition, but does not describe the comparison view separately, so confirm it on the instance.

The summary reports `submitted_unverified` when submission and flush complete; as with Cloud, only the UI or a read-API check confirms that the data is stored.

## Not covered

* Deploying and operating the Langfuse instance itself (infrastructure, backups, upgrades, access control).
* Migrating experiments and traces already stored in Langfuse Cloud. A new instance starts empty; rerun the experiments that are needed for comparison, using the same dataset and settings.

## Sources

Checked on 2026-11-09:

* [Langfuse self-hosted pricing and feature comparison](https://langfuse.com/pricing-self-host)
* [Langfuse self-hosting license key (Enterprise features)](https://langfuse.com/self-hosting/license-key)
* [Langfuse versions and compatibility](https://langfuse.com/docs/compatibility)
* [Python SDK v4 to v5 upgrade guide](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v4-to-v5)
* [Migrating self-hosted Langfuse from v3 to v4](https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v3-to-v4)
* [Changelog: Python SDK v5 and JS/TS SDK v6](https://langfuse.com/changelog/2026-10-14-python-sdk-v5-js-sdk-v6)
