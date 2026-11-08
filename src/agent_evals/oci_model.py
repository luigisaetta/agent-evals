"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Call OCI Responses using IAM user-principal request signing.
"""

import json

import httpx
from oci_genai_auth import OciUserPrincipalAuth
from openai import OpenAI

from agent_evals.config import Settings


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


def create_client(settings: Settings) -> OpenAI:
    """Build a Responses client signed with the user's OCI configuration.

    Args:
        settings: Validated OCI region, project, profile and request limits.

    Returns:
        OpenAI-compatible SDK client targeting OCI, with automatic retries off.
    """
    auth = SingleAttemptUserPrincipalAuth(
        config_file=str(settings.config_file), profile_name=settings.profile,
    )
    return OpenAI(
        base_url=f"https://inference.generativeai.{settings.region}.oci.oraclecloud.com/openai/v1",
        api_key="not-used", project=settings.project_id,
        http_client=httpx.Client(auth=auth, timeout=settings.timeout_seconds),
        timeout=settings.timeout_seconds, max_retries=0,
    )


def invoke_model(client: OpenAI, settings: Settings, instructions: str, task_input: object) -> dict:
    """Invoke one stateless OCI Responses request.

    Args:
        client: OCI-signed SDK client.
        settings: Model identifier and token limit.
        instructions: Final instructions assembled by the selected task adapter.
        task_input: JSON-serializable task input, without expected answers.

    Returns:
        Raw text, response status and identifier, and available token usage.
    """
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
