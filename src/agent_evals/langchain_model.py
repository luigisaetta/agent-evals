"""
Author: L. Saetta
Date last modified: 2026-11-10
License: MIT
Description: Adapt native LangChain OCI chat to the shared model response contract.
"""

import json

import oci
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_oci import ChatOCIGenAI

from agent_evals.config import Settings


class SingleAttemptChatOCIGenAI(ChatOCIGenAI):
    """Disable parameter repair/retry in the pinned langchain-oci 0.4.0 hook."""

    def _chat_with_param_retry(self, request):
        """Submit the original chat request exactly once.

        Args:
            request: Native OCI chat details assembled by LangChain.

        Returns:
            Native OCI response, without parameter changes or resubmission.
        """
        return self.client.chat(request, retry_strategy=oci.retry.NoneRetryStrategy())


def normalize_response(result) -> dict:
    """Translate a LangChain generation without inventing provider metadata.

    Args:
        result: LLMResult returned by one non-streaming chat generation.

    Returns:
        Shared text/status/ID/usage envelope; unknown finishes are not successful.
    """
    message = result.generations[0][0].message
    metadata = message.response_metadata
    finish = metadata.get("finish_reason") or message.additional_kwargs.get(
        "finish_reason"
    )
    reason = str(finish or "").upper()
    if reason in {"COMPLETE", "STOP"}:
        status = "completed"
    elif reason in {"MAX_TOKENS", "LENGTH"}:
        status = "incomplete"
    elif reason in {"ERROR_TOXIC", "CONTENT_FILTER"}:
        status = "blocked"
    elif reason in {"ERROR", "ERROR_LIMIT", "USER_CANCEL", "TOOL_CALL"}:
        status = "failed"
    else:
        status = "unknown"
    # These demos require plain text and never request tool calls or multimodal output.
    if not isinstance(message.content, str) or message.tool_calls:
        status = "failed"
    usage = message.usage_metadata or {}
    return {
        "raw_output": message.content if isinstance(message.content, str) else "",
        "response_status": status,
        "response_id": metadata.get("request_id")
        or (result.llm_output or {}).get("request_id"),
        "usage": {
            target: usage[source]
            for source, target in (
                ("input_tokens", "input"),
                ("output_tokens", "output"),
                ("total_tokens", "total"),
            )
            if source in usage
        },
    }


class LangChainOCIClient:
    """Own a native OCI chat client and expose the shared invocation contract."""

    def __init__(self, settings: Settings, provider: str):
        """Create an OCI user-principal client with explicit request limits.

        Args:
            settings: Environment-derived model, compartment, profile and limits.
            provider: Provider selected by the exact-model compatibility registry.
        """
        config = oci.config.from_file(str(settings.config_file), settings.profile)
        endpoint = (
            f"https://inference.generativeai.{settings.region}.oci.oraclecloud.com"
        )
        self.client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            config,
            service_endpoint=endpoint,
            timeout=settings.timeout_seconds,
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )
        try:
            self.model = SingleAttemptChatOCIGenAI(
                client=self.client,
                model_id=settings.model,
                provider=provider,
                compartment_id=settings.compartment_id,
                service_endpoint=endpoint,
                model_kwargs={"max_tokens": settings.max_output_tokens},
                use_responses_api=False,
                is_stream=False,
                cache=False,
                output_version="v0",
            )
        except Exception:
            self.client.base_client.session.close()
            raise

    def __enter__(self):
        """Return this adapter for the existing context-managed runner."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Close the owned OCI HTTP session even after a failed invocation.

        Args:
            exc_type: Exception type, if the context failed.
            exc_value: Exception instance, if present.
            traceback: Exception traceback, if present.
        """
        self.client.base_client.session.close()

    def invoke(self, instructions: str, task_input: object) -> dict:
        """Generate once using only the task instructions and serialized input.

        Args:
            instructions: Existing task prompt with no reference answers.
            task_input: JSON-compatible input for this step only.

        Returns:
            Normalized raw model response for the existing parsers/evaluators.
        """
        messages = [
            SystemMessage(content=instructions),
            HumanMessage(content=json.dumps(task_input, ensure_ascii=False)),
        ]
        return normalize_response(self.model.generate([messages]))
