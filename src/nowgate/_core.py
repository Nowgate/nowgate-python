"""What the generated resources build on: the response alongside its data, and the
requests a resource makes through the client."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Generic, Iterator, Mapping, Optional, Protocol, Sequence, TypeVar, Union

T = TypeVar("T")

AmountInput = Union[str, int, Decimal]
"""What an amount field takes: a decimal string such as "12.5", an int, or a finite
Decimal. A float is refused before sending: amounts are exact."""


@dataclass(frozen=True)
class APIResponse(Generic[T]):
    """The answer alongside its data, from a call through client.with_response."""

    data: T
    status: int
    headers: Mapping[str, str]
    """The answer's headers, by lowercase name."""
    request_id: Optional[str]
    """The request's ID (X-Request-Id), to quote to support."""
    idempotency_key: Optional[str]
    """The idempotency key a POST was sent with."""
    idempotent_replayed: bool
    """The API replayed the answer it stored for this key: the call had already been made."""


class Requester(Protocol):
    """What the resources call: the client's requests and pages."""

    def request(
        self,
        method: str,
        path: str,
        *,
        path_params: Optional[Mapping[str, str]] = None,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        amounts: Sequence[str] = (),
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> APIResponse[Any]: ...

    def paginate(
        self,
        path: str,
        *,
        query: Dict[str, Any],
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[Any]: ...


class Resource:
    """A group of operations, such as payments, answering with the data."""

    _with_response = False

    def __init__(self, client: Requester) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        return response if self._with_response else response.data

    def _paginate(self, path: str, **kwargs: Any) -> Iterator[Any]:
        return self._client.paginate(path, **kwargs)


class ResourceWithResponse(Resource):
    """A group of operations answering with the response alongside the data."""

    _with_response = True
