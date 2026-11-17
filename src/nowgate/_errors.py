"""The SDK's errors. Every problem the API answers with (RFC 9457 problem JSON) becomes an
ApiError of its status's class, carrying the whole problem."""

from __future__ import annotations

import json
import math
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Type, cast

from ._generated.types import FieldError


class NowgateError(Exception):
    """Every error the SDK raises, except a TypeError or ValueError for an argument it
    can't send."""


class ApiError(NowgateError):
    """A problem the API answered with."""

    status: int
    """The HTTP status."""
    code: str
    """The problem's stable code, such as insufficient_balance; http_<status> for an
    answer that isn't a problem."""
    title: str
    detail: Optional[str]
    type: Optional[str]
    """The code's page in the docs."""
    instance: Optional[str]
    request_id: Optional[str]
    """The request's ID, to quote to support."""
    retry_after: Optional[int]
    """The seconds the API asked to wait before trying again (Retry-After)."""
    errors: List[FieldError]
    """Each field's problem, with its JSON pointer into the request: /amount."""
    headers: Mapping[str, str]
    """The answer's headers, by lowercase name."""

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: Optional[str] = None,
        type: Optional[str] = None,
        instance: Optional[str] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[int] = None,
        errors: Optional[List[FieldError]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        page = f" ({type})" if type else ""
        super().__init__(f"{code}: {detail or title}{page}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.type = type
        self.instance = instance
        self.request_id = request_id
        self.retry_after = retry_after
        self.errors = errors if errors is not None else []
        self.headers = headers if headers is not None else {}


class AuthenticationError(ApiError):
    """401: the key is missing, unknown or revoked."""


class PermissionDeniedError(ApiError):
    """403: the key may not do this (insufficient_scope, ip_not_allowed, ...)."""


class NotFoundError(ApiError):
    """404: there's no such object, or it isn't yours."""


class ConflictError(ApiError):
    """409: the object's state doesn't allow this now."""


class InvalidRequestError(ApiError):
    """400, 405, 413, 414, 415 and 422: the request itself is wrong; errors points at the
    fields."""


class RateLimitError(ApiError):
    """429: too many requests; retry_after says when to try again."""


class ServerError(ApiError):
    """5xx: Nowgate couldn't answer. A POST's retry with the same idempotency key is safe."""


class APIConnectionError(NowgateError):
    """No answer: the connection was refused or reset, or an attempt timed out."""


SignatureFailure = Literal["malformed", "no_signature", "timestamp", "mismatch"]
"""Why a webhook's signature didn't verify: the published vectors' names."""

_FAILURES: Dict[str, str] = {
    "malformed": "the Nowgate-Signature header can't be parsed",
    "no_signature": "the Nowgate-Signature header has no v1 signature",
    "timestamp": "the signature's timestamp is outside the tolerance",
    "mismatch": "no signature matches the body with any of the secrets",
}


class SignatureVerificationError(NowgateError):
    """A webhook whose Nowgate-Signature doesn't verify: don't trust its body."""

    reason: SignatureFailure

    def __init__(self, reason: SignatureFailure) -> None:
        super().__init__(f"{reason}: {_FAILURES[reason]}")
        self.reason = reason


_STATUS_CLASSES: Dict[int, Type[ApiError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    405: InvalidRequestError,
    409: ConflictError,
    413: InvalidRequestError,
    414: InvalidRequestError,
    415: InvalidRequestError,
    422: InvalidRequestError,
    429: RateLimitError,
}

_JSON = re.compile(r"\bjson\b", re.IGNORECASE)


def api_error(
    status: int,
    reason: str,
    headers: Mapping[str, str],
    body: bytes,
    now: Optional[float] = None,
) -> ApiError:
    """The error for an answer that isn't a success. headers are by lowercase name."""
    problem = _parse_problem(headers, body)
    error_class = _STATUS_CLASSES.get(status) or (ServerError if status >= 500 else ApiError)
    retry_after = parse_retry_after(headers.get("retry-after"), now)
    if problem is not None:
        return error_class(
            status=status,
            code=cast(str, problem["code"]),
            title=cast(str, problem["title"]),
            detail=_text(problem, "detail"),
            type=_text(problem, "type"),
            instance=_text(problem, "instance"),
            request_id=_text(problem, "request_id") or headers.get("x-request-id"),
            retry_after=retry_after,
            errors=problem["errors"] if isinstance(problem.get("errors"), list) else None,
            headers=headers,
        )
    return error_class(
        status=status,
        code=f"http_{status}",
        title=reason or f"HTTP {status}",
        detail=_first_bytes(body, 500) or None,
        request_id=headers.get("x-request-id"),
        retry_after=retry_after,
        headers=headers,
    )


def _parse_problem(headers: Mapping[str, str], body: bytes) -> Optional[Dict[str, Any]]:
    """RFC 9457 problem JSON with a code and a title, or None for anything else."""
    if not _JSON.search(headers.get("content-type", "")):
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("code"), str) or not isinstance(value.get("title"), str):
        return None
    return value


def _text(problem: Dict[str, Any], key: str) -> Optional[str]:
    value = problem.get(key)
    return value if isinstance(value, str) else None


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[int]:
    """Retry-After, in seconds or as an HTTP date, as whole seconds from now."""
    if value is None:
        return None
    text = value.strip()
    if re.fullmatch(r"[0-9]+", text):
        return int(text)
    try:
        at = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if at.tzinfo is None:
        return None
    seconds = at.timestamp() - (time.time() if now is None else now)
    return max(0, math.ceil(seconds))


def _first_bytes(body: bytes, n: int) -> str:
    """The text of at most the first n bytes of body, as UTF-8, whole characters only."""
    if len(body) <= n:
        return body.decode("utf-8", errors="replace")
    end = n
    while end > 0 and (body[end] & 0xC0) == 0x80:  # not inside a character
        end -= 1
    return body[:end].decode("utf-8", errors="replace")
