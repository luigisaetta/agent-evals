"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Define and load the small adaptation contract for evaluation tasks.
"""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class EvaluationTask:
    """Describe the parts of an evaluation that depend on the business task.

    Attributes:
        name: Stable task identifier.
        title: Human-readable title for the banner and hosted dataset.
        default_dataset: Default dataset path relative to the repository root.
        default_rules: Default rules path relative to the repository root.
        rules_manifest_key: Rule-file key in the manifest's source_sha256 map.
        dataset_namespace: Prefix isolating this task's Langfuse dataset items.
        metric_name: Langfuse metric name for binary correctness.
        validate_case: Validate domain input/reference fields without relabeling.
        build_instructions: Build final model instructions from the rules text.
        parse_output: Parse model text using the task input; raise ValueError for
            invalid model output and return a JSON-compatible value otherwise.
        score_output: Compare parsed output to the reference and return 0 or 1.
        version: Version of the task's prompt, validation and evaluator behavior.
    """

    name: str
    title: str
    default_dataset: Path
    default_rules: Path
    rules_manifest_key: str
    dataset_namespace: str
    metric_name: str
    validate_case: Callable[[dict], None]
    build_instructions: Callable[[str], str]
    parse_output: Callable[[str, Any], Any]
    score_output: Callable[[Any, Any], int]
    version: str = "1.0"


def load_task(module_name: str) -> EvaluationTask:
    """Load an explicitly selected, trusted local task module.

    Args:
        module_name: Importable Python module exporting a TASK descriptor.

    Returns:
        Task settings and callbacks.

    Raises:
        ValueError: If the module cannot load or does not export a valid task.
    """
    try:
        task = getattr(import_module(module_name), "TASK", None)
    except ImportError as error:
        raise ValueError("Cannot import the selected task module") from error
    if not isinstance(task, EvaluationTask):
        raise ValueError("Task module must export TASK as an EvaluationTask")
    if any(not isinstance(value, str) or not value.strip() for value in (
        task.name, task.title, task.rules_manifest_key, task.dataset_namespace,
        task.metric_name, task.version,
    )):
        raise ValueError("Task identifiers, title and versions must be non-empty strings")
    if task.metric_name in {"valid_output", "execution_status"}:
        raise ValueError("Task metric name conflicts with a shared status metric")
    if not all(callable(callback) for callback in (
        task.validate_case, task.build_instructions, task.parse_output, task.score_output,
    )):
        raise ValueError("Task callbacks must be callable")
    return task
