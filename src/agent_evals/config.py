"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Load evaluation settings without exposing credentials.
"""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


class ConfigurationError(ValueError):
    """Report safe, actionable configuration errors without secret values."""


@dataclass(frozen=True)
class Settings:
    """Store non-secret OCI and evaluation settings.

    Attributes:
        region: OCI inference region.
        model: Model identifier or dedicated endpoint OCID.
        project_id: OCI Generative AI project OCID.
        config_file: OCI credential configuration file.
        profile: OCI user-principal profile name.
        sleep_seconds: Pause before each model call after the first.
        timeout_seconds: Timeout for each provider request.
        max_output_tokens: Maximum generated tokens per request.
    """

    region: str
    model: str
    project_id: str
    config_file: Path
    profile: str
    sleep_seconds: float
    timeout_seconds: float
    max_output_tokens: int


def required_env(name: str) -> str:
    """Read a required environment variable without echoing its value.

    Args:
        name: Environment variable name.

    Returns:
        Non-empty configured value.

    Raises:
        ValueError: If the variable is missing or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def load_settings(env_file: Path, sleep_override: float | None = None) -> Settings:
    """Load and validate settings, preserving existing environment variables.

    Args:
        env_file: Path to the ignored dotenv file.
        sleep_override: Optional CLI override for the inter-call pause.

    Returns:
        Validated settings, without Langfuse secrets.

    Raises:
        ValueError: If required variables or numeric settings are invalid.
    """
    load_dotenv(env_file, override=False, interpolate=False)
    region = required_env("OCI_REGION")
    if not re.fullmatch(r"[a-z]+-[a-z0-9]+-\d+", region):
        raise ConfigurationError("OCI_REGION must be a regional identifier")
    try:
        sleep = float(os.environ.get("EVAL_SLEEP_SECONDS", "2")) if sleep_override is None else sleep_override
        timeout = float(os.environ.get("OCI_TIMEOUT_SECONDS", "120"))
        max_tokens = int(os.environ.get("OCI_MAX_OUTPUT_TOKENS", "2048"))
    except ValueError as error:
        raise ConfigurationError("Sleep, timeout and token limit must be numeric") from error
    if not math.isfinite(sleep) or sleep < 0:
        raise ConfigurationError("Sleep seconds must be finite and non-negative")
    if not math.isfinite(timeout) or timeout <= 0 or max_tokens <= 0:
        raise ConfigurationError("Timeout and output token limit must be positive and finite")
    return Settings(
        region=region, model=required_env("OCI_MODEL"),
        project_id=required_env("OCI_PROJECT_ID"),
        config_file=Path(os.environ.get("OCI_CONFIG_FILE", "~/.oci/config")).expanduser(),
        profile=os.environ.get("OCI_PROFILE", "DEFAULT"), sleep_seconds=sleep,
        timeout_seconds=timeout, max_output_tokens=max_tokens,
    )
