"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Publish synthetic dataset items and evaluation scores to Langfuse.
"""

import hashlib

from langfuse import Evaluation, Langfuse

from agent_evals.config import required_env
from agent_evals.console import initialization_step
from agent_evals.task import EvaluationTask


def prepare_experiment(cases: list[dict], dataset_hash: str, split: str,
                       task: EvaluationTask, dataset_version: str, rules_version: str) -> tuple:
    """Validate Langfuse access and upsert the selected synthetic cases.

    Args:
        cases: Locally validated cases selected for this experiment.
        dataset_hash: SHA-256 of the complete source dataset.
        split: Selected dataset split, or all.
        task: Task namespace and display settings.
        dataset_version: Version read from the dataset manifest.
        rules_version: Version read from the dataset manifest.

    Returns:
        Langfuse client, uploaded dataset items and hosted dataset name.

    Raises:
        ValueError: If credentials are missing or authentication fails.
    """
    with initialization_step(5, "Initialize Langfuse client"):
        client = Langfuse(
            public_key=required_env("LANGFUSE_PUBLIC_KEY"),
            secret_key=required_env("LANGFUSE_SECRET_KEY"),
            base_url=required_env("LANGFUSE_BASE_URL"),
            timeout=30,
        )
    with initialization_step(6, "Verify Langfuse authentication"):
        if not client.auth_check():
            raise ValueError("Langfuse authentication failed")
    name = f"{task.dataset_namespace}-{split}-{dataset_hash[:12]}"
    with initialization_step(7, "Create or update Langfuse dataset"):
        client.create_dataset(
            name=name, description=f"{task.title} evaluation cases",
            metadata={"dataset_sha256": dataset_hash, "split": split,
                      "rules_version": rules_version, "dataset_version": dataset_version,
                      "task_name": task.name, "task_version": task.version},
        )
    items = []
    with initialization_step(8, f"Upload {len(cases)} selected cases to Langfuse"):
        for case in cases:
            item_id = hashlib.sha256(f"{name}:{case['id']}".encode()).hexdigest()
            items.append(client.create_dataset_item(
                dataset_name=name, id=item_id, input=case["input"],
                expected_output=case["expected_output"],
                metadata=case["metadata"] | {"case_id": case["id"]},
            ))
    return client, items, name


def make_evaluator(metric_name: str):
    """Create a domain-independent Langfuse adapter for precomputed scores.

    Args:
        metric_name: Correctness metric name supplied by the task.

    Returns:
        SDK evaluator publishing validity, execution status and binary correctness.
    """
    def evaluator(*, output: dict, **kwargs) -> list[Evaluation]:
        """Map a completed task result to SDK score objects.

        Args:
            output: Generic case result already parsed and scored by the task.
            **kwargs: Additional SDK fields; references are not rescored here.

        Returns:
            Status metrics, plus correctness when a valid score exists.
        """
        scores = [Evaluation(name="valid_output", value=int(output["output_valid"])),
                  Evaluation(name="execution_status", value=output["status"], data_type="CATEGORICAL")]
        if output["status"] in {"correct", "incorrect"}:
            scores.append(Evaluation(name=metric_name, value=output["score"]))
        return scores

    return evaluator
