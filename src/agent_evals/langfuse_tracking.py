"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Publish synthetic dataset items and evaluation scores to Langfuse.
"""

import hashlib

from langfuse import Evaluation, Langfuse

from agent_evals.config import required_env


def prepare_experiment(cases: list[dict], dataset_hash: str, split: str) -> tuple:
    """Validate Langfuse access and upsert the selected synthetic cases.

    Args:
        cases: Locally validated cases selected for this experiment.
        dataset_hash: SHA-256 of the complete source dataset.
        split: Selected dataset split, or all.

    Returns:
        Langfuse client, uploaded dataset items and hosted dataset name.

    Raises:
        ValueError: If credentials are missing or authentication fails.
    """
    client = Langfuse(
        public_key=required_env("LANGFUSE_PUBLIC_KEY"),
        secret_key=required_env("LANGFUSE_SECRET_KEY"),
        base_url=required_env("LANGFUSE_BASE_URL"),
        timeout=30,
    )
    if not client.auth_check():
        raise ValueError("Langfuse authentication failed")
    name = f"express-order-v1-{split}-{dataset_hash[:12]}"
    client.create_dataset(
        name=name, description="Synthetic Automotive Express Order selection cases",
        metadata={"dataset_sha256": dataset_hash, "split": split, "rules_version": "1.1"},
    )
    items = []
    for case in cases:
        item_id = hashlib.sha256(f"{name}:{case['id']}".encode()).hexdigest()
        items.append(client.create_dataset_item(
            dataset_name=name, id=item_id, input=case["input"],
            expected_output=case["expected_output"],
            metadata=case["metadata"] | {"case_id": case["id"]},
        ))
    return client, items, name


def selection_evaluator(*, output: dict, expected_output: dict, **kwargs) -> list[Evaluation]:
    """Score valid selections and separately report execution validity.

    Args:
        output: Task result including status and selected offer ID.
        expected_output: Dataset reference containing expected_offer_id.
        **kwargs: Additional fields supplied by the experiment SDK.

    Returns:
        A validity score for every attempt and exact-match score for valid output.
    """
    valid = output["status"] in {"correct", "incorrect"}
    scores = [Evaluation(name="valid_output", value=int(valid)),
              Evaluation(name="execution_status", value=output["status"], data_type="CATEGORICAL")]
    if valid:
        scores.append(Evaluation(
            name="selection_correct",
            value=int(output["selected_offer_id"] == expected_output["expected_offer_id"]),
        ))
    return scores
