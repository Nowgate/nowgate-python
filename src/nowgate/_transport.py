"""How the client sends a request: the standard library's urllib by default, or a
transport of your own, a function from a Request to a Response."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Request:
    """One attempt of a call, as the client sends it."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: Optional[bytes]
    timeout: float
    """Seconds the attempt may wait for the network."""


@dataclass(frozen=True)
class Response:
    """An answer, whatever its status. A transport that gets no answer raises an OSError."""

    status: int
    headers: Mapping[str, str]
    body: bytes = b""
    reason: str = ""


Transport = Callable[[Request], Response]
"""Sends one attempt and returns the answer, whatever its status. When there's no answer
(the connection is refused or reset, or the attempt times out), it raises an OSError, such
as ConnectionError or TimeoutError: the client retries those."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    # The API never redirects: an answer that does is returned as it is, not followed with
    # the key to wherever it points.
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass
class UrllibTransport:
    """The default transport: urllib from the standard library, following no redirects,
    with the system's certificates and the environment's proxy settings."""

    _opener: urllib.request.OpenerDirector = field(
        default_factory=lambda: urllib.request.build_opener(_NoRedirects()), repr=False
    )

    def __call__(self, request: Request) -> Response:
        attempt = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with self._opener.open(attempt, timeout=request.timeout) as answer:
                return Response(
                    status=answer.status,
                    headers=_headers(answer.headers.items()),
                    body=answer.read(),
                    reason=answer.reason or "",
                )
        except urllib.error.HTTPError as answer:
            # An answer whose status isn't a success: urllib raises it, the client reads it.
            with answer:
                return Response(
                    status=answer.code,
                    headers=_headers(answer.headers.items() if answer.headers else []),
                    body=answer.read(),
                    reason=str(answer.reason or ""),
                )


def _headers(items: Iterable[Tuple[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, value in items:
        key = str(name).lower()
        out[key] = f"{out[key]}, {value}" if key in out else str(value)
    return out
