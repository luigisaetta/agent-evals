"""
Author: L. Saetta
Date last modified: 2026-11-10
License: MIT
Description: Validate and dispatch shared OCI model calls through the selected interface.
"""

import json

import httpx
from oci_genai_auth import OciUserPrincipalAuth
from openai import OpenAI

from agent_evals.config import ConfigurationError, Settings

# Exact IDs only. Evidence and extension policy: specs/model-interfaces.md.
MODEL_INTERFACES = {
    "openai.gpt-oss-20b": ("openai", {"responses"}),
    "openai.gpt-oss-120b": ("openai", {"responses"}),
    "openai.gpt-6.1-terra": ("openai", {"responses"}),
    "google.gemini-2.5-pro": ("google", {"responses"}),
    "google.gemini-2.5-flash": ("google", {"responses"}),
    "google.gemini-2.5-flash-lite": ("google", {"responses"}),
    "cohere.command-a-03-2025": ("cohere", {"langchain_oci"}),
    "meta.llama-3.3-70b-instruct": ("meta", {"langchain_oci"}),
    "meta.llama-4-scout-17b-16e-instruct": ("meta", {"langchain_oci"}),
}


def validate_model_interface(settings: Settings) -> str:
    """Check exact model compatibility before creating any external client.

    Args:
        settings: Selected interface, model identity and OCI configuration.

    Returns:
        Provider name for the verified model/interface combination.

    Raises:
        ConfigurationError: If the combination is unknown or incompatible.
    """
    if settings.model_interface not in {"responses", "langchain_oci"}:
        raise ConfigurationError("OCI_MODEL_INTERFACE must be responses or langchain_oci")
    dedicated = settings.model.startswith("ocid1.generativeaiendpoint.")
    if dedicated and not settings.model_name:
        raise ConfigurationError("Dedicated endpoints require OCI_MODEL_NAME for compatibility checks")
    if not dedicated and settings.model_name:
        raise ConfigurationError("OCI_MODEL_NAME is only allowed with a dedicated endpoint")
    identity = settings.model_name if dedicated else settings.model
    entry = MODEL_INTERFACES.get(identity)
    if entry is None:
        raise ConfigurationError(
            "OCI_MODEL is not in the verified compatibility registry; see specs/model-interfaces.md"
        )
    provider, interfaces = entry
    if settings.model_interface not in interfaces:
        raise ConfigurationError(
            "OCI_MODEL does not support the selected OCI_MODEL_INTERFACE in this project; "
            f"use one of: {', '.join(sorted(interfaces))}"
        )
    required = settings.project_id if settings.model_interface == "responses" else settings.compartment_id
    if not required:
        variable = "OCI_PROJECT_ID" if settings.model_interface == "responses" else "OCI_COMPARTMENT_ID"
        raise ConfigurationError(f"Missing required environment variable: {variable}")
    return provider


class SingleAttemptUserPrincipalAuth(OciUserPrincipalAuth):
    """Use Oracle signing while preventing its automatic 401 retry."""

    def auth_flow(self, request: httpx.Request):
        """Sign exactly one request through the Oracle authentication helper.

        Args:
            request: HTTP request to sign.

        Yields:
            The signed request, without resubmission after authentication errors.
        """
        flow = super().auth_flow(request)
        try:
            yield next(flow)
        finally:
            flow.close()


def create_client(settings: Settings):
    """Build a context-managed client for the selected, validated OCI interface.

    Args:
        settings: Validated OCI region, project, profile and request limits.

    Returns:
        Responses or native-chat adapter, with automatic retries off.
    """
    provider = validate_model_interface(settings)
    if settings.model_interface == "langchain_oci":
        from agent_evals.langchain_model import LangChainOCIClient

        return LangChainOCIClient(settings, provider)
    auth = SingleAttemptUserPrincipalAuth(
        config_file=str(settings.config_file), profile_name=settings.profile,
    )
    return OpenAI(
        base_url=f"https://inference.generativeai.{settings.region}.oci.oraclecloud.com/openai/v1",
        api_key="not-used", project=settings.project_id,
        http_client=httpx.Client(auth=auth, timeout=settings.timeout_seconds),
        timeout=settings.timeout_seconds, max_retries=0,
    )


def invoke_model(client, settings: Settings, instructions: str, task_input: object) -> dict:
    """Invoke one stateless request through the configured OCI interface.

    Args:
        client: OCI-signed SDK client.
        settings: Model identifier and token limit.
        instructions: Final instructions assembled by the selected task adapter.
        task_input: JSON-serializable task input, without expected answers.

    Returns:
        Raw text, response status and identifier, and available token usage.
    """
    if getattr(settings, "model_interface", "responses") == "langchain_oci":
        return client.invoke(instructions, task_input)
    response = client.responses.create(
        model=settings.model, instructions=instructions,
        input=json.dumps(task_input, ensure_ascii=False),
        max_output_tokens=settings.max_output_tokens, store=False,
    )
    usage = response.usage
    return {
        "raw_output": response.output_text,
        "response_status": response.status,
        "response_id": response.id,
        "usage": ({"input": usage.input_tokens, "output": usage.output_tokens,
                   "total": usage.total_tokens} if usage else {}),
    }
