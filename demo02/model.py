"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Pace shared OCI Responses calls across both Demo02 agent steps.
"""

import time

from openai import OpenAI

from agent_evals.config import Settings
from agent_evals.oci_model import invoke_model


class PacedResponses:
    """Call the same configured OCI model sequentially with an inter-call pause."""

    def __init__(self, client: OpenAI, settings: Settings):
        """Bind the existing signed client and environment-derived settings.

        Args:
            client: Client created through the shared OCI signing implementation.
            settings: Model, token/timeout limits, and sleep configuration.
        """
        self.client = client
        self.settings = settings
        self._called = False

    def __call__(self, instructions: str, task_input: object) -> dict:
        """Issue one Responses request after the configured inter-call pause.

        Args:
            instructions: Instructions for the current graph step.
            task_input: Only the payload required by this step.

        Returns:
            The shared Responses result envelope.
        """
        if self._called:
            time.sleep(self.settings.sleep_seconds)
        self._called = True
        return invoke_model(self.client, self.settings, instructions, task_input)
