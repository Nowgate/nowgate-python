"""A fake transport for the unit tests: it answers each request from a script and records
what it was sent, and the client's waits between attempts are recorded instead of slept."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from nowgate import Nowgate, Request, Response

SDK = Path(__file__).resolve().parents[1]
"""The SDK's own directory: its pyproject.toml, and testdata/ when it stands alone."""

ROOT = SDK.parent.parent
"""Nowgate's repository, when the SDK is in it: the published vectors and the spec."""


def fixture(path: str) -> Path:
    """A file the SDKs' tests share, by its path in Nowgate's repository: from this SDK's
    testdata/ when the SDK stands alone, as in its public repository, else from the
    repository's own path."""
    local = SDK / "testdata" / Path(path).name
    return local if local.exists() else ROOT / path

SECRET = "0123456789" * 4 + "abc"
"""A test key's secret: low-entropy, so no secret scanner mistakes it for a real one."""
KEY = f"ngk_sandbox_{SECRET}"

Answer = Union[Response, BaseException, Callable[[Request], Response]]

PAYMENT: Dict[str, Any] = {
    "id": "pay_01m6k00000000000000000000a",
    "object": "payment",
    "status": "waiting",
    "network": "tron",
    "asset": "USDT",
    "amount": "25",
}


def answer(status: int, body: Any, headers: Optional[Dict[str, str]] = None) -> Response:
    """A JSON answer."""
    return Response(
        status=status,
        headers={"content-type": "application/json", **(headers or {})},
        body=json.dumps(body).encode(),
    )


def problem(
    status: int,
    code: str,
    headers: Optional[Dict[str, str]] = None,
    **extra: Any,
) -> Response:
    """RFC 9457 problem JSON, as the API answers."""
    body = {
        "type": f"https://docs.nowgate.io/errors/{code}",
        "title": "Problem",
        "status": status,
        "code": code,
        "detail": f"The {code} detail.",
        "instance": "/v1/payments",
        "request_id": "req_problem",
        **extra,
    }
    return Response(
        status=status,
        headers={"content-type": "application/problem+json", **(headers or {})},
        body=json.dumps(body).encode(),
    )


def refused() -> OSError:
    """What a transport raises when nothing listens."""
    return ConnectionRefusedError(111, "Connection refused")


class Fake:
    """A client whose transport answers from a script."""

    def __init__(self, answers: Sequence[Answer], random: float = 1.0, **options: Any) -> None:
        self.answers = list(answers)
        self.sent: List[Request] = []
        self.waits: List[float] = []
        self.client = Nowgate(KEY, transport=self, **options)
        requester = self.client._requester
        requester._sleep = self.waits.append
        requester._random = lambda: random

    def __call__(self, request: Request) -> Response:
        self.sent.append(request)
        if not self.answers:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(request)
        return answer

    def body(self, i: int) -> Any:
        """The JSON body of request i."""
        body = self.sent[i].body
        assert body is not None
        return json.loads(body)
