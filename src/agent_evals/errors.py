"""
Author: L. Saetta
Date last modified: 2026-11-10
License: MIT
Description: Classify API and transport failures without exposing sensitive details.
"""

import socket
import ssl

import httpx
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError as RequestsSSLError
from requests.exceptions import Timeout as RequestsTimeout


def describe_api_error(error: Exception) -> dict:
    """Describe provider failures without exposing raw exception messages.

    Args:
        error: Provider exception, possibly wrapping a transport failure.

    Returns:
        Safe exception types, HTTP status and a readable failure category.
    """
    status_code = getattr(error, "status_code", None) or getattr(error, "status", None)
    current = error
    seen = set()
    reason = None
    cause_type = type(error).__name__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        cause_type = type(current).__name__
        for exception_type, category in (
            (socket.gaierror, "DNS resolution failed"),
            (ssl.SSLError, "TLS certificate or handshake failed"),
            (RequestsConnectionError, "Connection failed"),
            (RequestsSSLError, "TLS certificate or handshake failed"),
            (RequestsTimeout, "Request timed out"),
            (httpx.TimeoutException, "Request timed out"),
            (TimeoutError, "Request timed out"),
            (httpx.ProxyError, "Proxy connection failed"),
            (ConnectionRefusedError, "Connection refused"),
        ):
            if isinstance(current, exception_type):
                reason = category
        current = current.__cause__ or current.__context__
    return {
        "type": type(error).__name__,
        "http_status": status_code if isinstance(status_code, int) else None,
        "cause_type": cause_type,
        "reason": reason or cause_type,
    }
