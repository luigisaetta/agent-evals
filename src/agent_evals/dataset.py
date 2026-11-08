"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Load evaluation case envelopes and verify manifest provenance.
"""

import hashlib
import json
from pathlib import Path

from agent_evals.task import EvaluationTask


def file_hash(path: Path) -> str:
    """Compute a source artifact hash.

    Args:
        path: File to hash.

    Returns:
        Hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(dataset_path: Path, rules_path: Path, split: str, limit: int | None,
               task: EvaluationTask) -> list[dict]:
    """Validate the dataset and select cases before making external calls.

    Args:
        dataset_path: Dataset JSON file.
        rules_path: Rules file whose provenance must match the dataset manifest.
        split: Evaluation, development, or all cases.
        limit: Optional positive maximum number of cases.
        task: Domain validation and manifest configuration.

    Returns:
        Selected validated cases in their stored order.

    Raises:
        ValueError: If schema, labels, provenance, or selection are invalid.
    """
    if split not in {"evaluation", "development", "all"}:
        raise ValueError("Unknown dataset split")
    if limit is not None and limit <= 0:
        raise ValueError("Case limit must be positive")
    manifest = json.loads(dataset_path.with_suffix(".manifest.json").read_text())
    if manifest["dataset_sha256"] != file_hash(dataset_path):
        raise ValueError("Dataset hash differs from its manifest")
    if manifest["source_sha256"][task.rules_manifest_key] != file_hash(rules_path):
        raise ValueError("Rule contents differ from the dataset's reference rules")
    cases = json.loads(dataset_path.read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must be a non-empty array")
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "input", "expected_output", "metadata"}:
            raise ValueError("Invalid dataset case fields")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in identifiers:
            raise ValueError("Case identifiers must be unique non-empty strings")
        identifiers.add(case_id)
        if not isinstance(case["metadata"], dict):
            raise ValueError(f"Case metadata must be an object: {case_id}")
        if case["metadata"].get("split") not in {"development", "evaluation"}:
            raise ValueError(f"Missing or invalid split: {case_id}")
        if case["metadata"].get("rules_version") != manifest["rules_version"]:
            raise ValueError(f"Rules version mismatch: {case_id}")
        if case["metadata"].get("dataset_version") != manifest["dataset_version"]:
            raise ValueError(f"Dataset version mismatch: {case_id}")
        task.validate_case(case)
    selected = [c for c in cases if split == "all" or c["metadata"]["split"] == split]
    if not selected:
        raise ValueError("No cases selected")
    return selected[:limit] if limit is not None else selected
