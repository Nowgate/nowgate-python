"""The Nowgate client: keys and environments, requests with safe retries and idempotency
keys, pages, amounts refused as floats, and problems as errors (api-docs-and-sdks.md,
sections 1 and 2; ADR 0032)."""

from __future__ import annotations

import http.client
import json
import math
import platform
import random
import re
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode, urlsplit

from ._amounts import amount_text
from ._core import APIResponse
from ._errors import ApiError, APIConnectionError, NowgateError, api_error
from ._generated.resources import Resources, ResourcesWithResponse
from ._generated.types import VERSION
from ._transport import Request, Response, Transport, UrllibTransport

_BASE_URLS = {
    "live": "https://api.nowgate.io/v1",
    "sandbox": "https://sandbox-api.nowgate.io/v1",
}
_KEY = re.compile(r"ngk_([a-z]+)_([\x21-\x7e]+)")
_APP_INFO = re.compile(r"[\x21-\x7e]+( [\x21-\x7e]+)*")
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
# The longest Retry-After waited for, in seconds; a longer one is the caller's to handle.
_MAX_RETRY_AFTER = 60
_FIRST_BACKOFF = 0.5
_MAX_BACKOFF = 8.0
_RETRIED_STATUSES = {429, 500, 502, 503, 504}


class Nowgate(Resources):
    """The Nowgate API's client.

    >>> client = Nowgate(api_key=os.environ["NOWGATE_API_KEY"])
    >>> payment = client.payments.create(network="tron", asset="USDT", amount="25")

    The key's environment picks the API: https://api.nowgate.io/v1 for a live key and
    https://sandbox-api.nowgate.io/v1 for a sandbox key. Other keys need a base_url.
    client.with_response makes the same calls, answering with an APIResponse: the data
    with the status, the headers, the request's ID and the idempotency facts.
    """

    base_url: str
    """The API's base URL, without a trailing slash."""
    timeout: float
    """Seconds each attempt may wait for the network."""
    max_retries: int
    """How many times a failed attempt is retried."""
    with_response: ResourcesWithResponse
    """The same calls, answering with the response alongside the data."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: Optional[Transport] = None,
        app_info: Optional[str] = None,
    ) -> None:
        requester = _Requester(api_key, base_url, timeout, max_retries, transport, app_info)
        super().__init__(requester)
        self._requester = requester
        self.with_response = ResourcesWithResponse(requester)
        self.base_url = requester.base_url
        self.timeout = requester.timeout
        self.max_retries = requester.max_retries

    def __repr__(self) -> str:
        return (
            f"Nowgate(api_key={self._requester.key_hint!r}, base_url={self.base_url!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r})"
        )


class _Requester:
    """Sends the resources' requests. It holds the key, which nothing shows."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str],
        timeout: float,
        max_retries: int,
        transport: Optional[Transport],
        app_info: Optional[str],
    ) -> None:
        match = _KEY.fullmatch(api_key) if isinstance(api_key, str) else None
        if match is None:
            raise TypeError("api_key must be a Nowgate API key: ngk_live_... or ngk_sandbox_...")
        env, secret = match.group(1), match.group(2)
        hint = f"{secret[:6]}…{secret[-4:]}" if len(secret) >= 16 else "…"
        self.key_hint = f"ngk_{env}_{hint}"
        base = base_url if base_url is not None else _BASE_URLS.get(env)
        if base is None:
            raise TypeError(f"A {env} key needs a base_url: only live and sandbox keys have one")
        self.base_url = _base_url(base, env)
        self.timeout = _seconds(timeout)
        self.max_retries = _retries(max_retries)
        if transport is not None and not callable(transport):
            raise TypeError("transport must be a function from a Request to a Response")
        self._transport: Transport = transport if transport is not None else UrllibTransport()
        self._key = _Secret(f"Bearer {api_key}", self.key_hint)
        self._user_agent = _user_agent(app_info)
        # The waits between attempts: the SDK's own tests replace them.
        self._sleep: Callable[[float], None] = time.sleep
        self._random: Callable[[], float] = random.random

    def __repr__(self) -> str:
        return f"<nowgate requester {self.key_hint} {self.base_url}>"

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
    ) -> APIResponse[Any]:
        if body is not None:
            body = _with_amounts({k: v for k, v in body.items() if v is not None}, amounts)
        if query is not None:
            query = _with_amounts({k: v for k, v in query.items() if v is not None}, amounts)
        url = self._url(path, path_params or {}, query or {})
        seconds = _seconds(self.timeout if timeout is None else timeout)
        retries = _retries(self.max_retries if max_retries is None else max_retries)
        headers = {
            "Accept": "application/json",
            "Authorization": self._key.value,
            "User-Agent": self._user_agent,
        }
        key: Optional[str] = None
        if method == "POST":
            key = str(uuid.uuid4()) if idempotency_key is None else idempotency_key
            if not isinstance(key, str) or key == "":
                raise TypeError("idempotency_key must be a non-empty string, such as a UUID")
            headers["Idempotency-Key"] = key
        data: Optional[bytes] = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        attempt = Request(method=method, url=url, headers=headers, body=data, timeout=seconds)

        tries = 0
        while True:
            try:
                answer = self._transport(attempt)
            except (OSError, http.client.HTTPException) as err:
                if tries >= retries:
                    raise self._unreachable(err, seconds) from err
                self._sleep(self._backoff(tries))
                tries += 1
                continue
            if not isinstance(answer, Response):
                raise TypeError("the transport must return a nowgate.Response")
            answered = {str(k).lower(): str(v) for k, v in answer.headers.items()}
            if 200 <= answer.status < 300:
                return APIResponse(
                    data=_decode(answer),
                    status=answer.status,
                    headers=answered,
                    request_id=answered.get("x-request-id"),
                    idempotency_key=key,
                    idempotent_replayed=answered.get("idempotent-replayed") == "true",
                )
            error = api_error(answer.status, answer.reason, answered, answer.body)
            if tries >= retries or not _retryable(error):
                raise error
            wait = self._backoff(tries)
            if error.retry_after is not None:
                if error.retry_after > _MAX_RETRY_AFTER:
                    raise error
                wait = float(error.retry_after)
            self._sleep(wait)
            tries += 1

    def paginate(
        self,
        path: str,
        *,
        query: Dict[str, Any],
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Iterator[Any]:
        if query.get("ending_before") is not None:
            raise TypeError("list_all walks from the newest item down: give starting_after, not ending_before")
        walk = dict(query)
        if walk.get("limit") is None:
            walk["limit"] = 100
        return self._walk(path, walk, timeout, max_retries)

    def _walk(
        self,
        path: str,
        query: Dict[str, Any],
        timeout: Optional[float],
        max_retries: Optional[int],
    ) -> Iterator[Any]:
        while True:
            page = self.request("GET", path, query=query, timeout=timeout, max_retries=max_retries).data
            items: List[Any] = page["data"]
            yield from items
            if not page["has_more"] or not items:
                return
            query["starting_after"] = items[-1]["id"]

    def _unreachable(self, err: BaseException, timeout: float) -> APIConnectionError:
        reason = getattr(err, "reason", None)
        if isinstance(err, TimeoutError) or isinstance(reason, TimeoutError):
            return APIConnectionError(f"Nowgate didn't answer within {timeout:g} s")
        why = reason if reason is not None else err
        return APIConnectionError(f"Couldn't reach Nowgate at {self.base_url}: {why}")

    def _backoff(self, attempt: int) -> float:
        """The wait before retry number attempt+1: exponential, with full jitter."""
        return min(_MAX_BACKOFF, _FIRST_BACKOFF * 2.0 ** min(attempt, 16)) * self._random()

    def _url(self, path: str, path_params: Mapping[str, str], query: Dict[str, Any]) -> str:
        def fill(match: "re.Match[str]") -> str:
            name = match.group(1)
            value = path_params.get(name)
            if not isinstance(value, str) or value == "":
                raise TypeError(f"{name} must be a non-empty string: an object's ID")
            return quote(value, safe="")

        url = self.base_url + re.sub(r"\{([^}]+)\}", fill, path)
        pairs: List[Tuple[str, str]] = []
        for name, value in query.items():
            if isinstance(value, bool):
                pairs.append((name, "true" if value else "false"))
            elif isinstance(value, (str, int)):
                pairs.append((name, str(value)))
            else:
                raise TypeError(f"The query parameter {name} must be a string, an int or a bool")
        return f"{url}?{urlencode(pairs)}" if pairs else url


class _Secret:
    """The Authorization header's value, shown only as the key's hint."""

    __slots__ = ("value", "_hint")

    def __init__(self, value: str, hint: str) -> None:
        self.value = value
        self._hint = hint

    def __repr__(self) -> str:
        return f"<secret {self._hint}>"

    __str__ = __repr__


def _retryable(error: ApiError) -> bool:
    """Whether the API's answer may change on a retry (ADR 0032)."""
    if error.status == 409:
        return error.code == "idempotency_key_in_progress"
    return error.status in _RETRIED_STATUSES


def _decode(answer: Response) -> Any:
    if answer.body == b"":
        return None
    try:
        return json.loads(answer.body.decode("utf-8"))
    except ValueError as err:
        raise NowgateError(f"Nowgate answered {answer.status} with a body that isn't JSON") from err


def _with_amounts(payload: Dict[str, Any], pointers: Sequence[str]) -> Dict[str, Any]:
    """payload with its amounts as the API reads them: ints and Decimals as decimal strings,
    floats refused. The caller's own dicts and lists are copied, never changed."""
    out: Any = payload
    for pointer in pointers:
        out = _visit(out, pointer.split("/")[1:], "")
    return dict(out)


def _visit(value: Any, path: List[str], at: str) -> Any:
    if not path:
        return amount_text(value, at)
    segment, rest = path[0], path[1:]
    if segment == "*":
        if isinstance(value, list):
            return [_visit(item, rest, f"{at}/{i}") for i, item in enumerate(value)]
        return value
    key = segment.replace("~1", "/").replace("~0", "~")
    if isinstance(value, dict) and key in value:
        copy = dict(value)
        copy[key] = _visit(value[key], rest, f"{at}/{segment}")
        return copy
    return value


def _base_url(base: str, env: str) -> str:
    if not isinstance(base, str):
        raise TypeError("base_url must be a URL")
    url = urlsplit(base)
    if url.scheme not in ("https", "http") or not url.netloc:
        raise TypeError(f"base_url must be an https URL: {base}")
    if url.scheme == "http" and env in ("live", "sandbox"):
        raise TypeError(f"A {env} key is sent only over https")
    if url.query or url.fragment or base.endswith(("?", "#")):
        raise TypeError("base_url can't have a query or a fragment")
    return base.rstrip("/")


def _seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise TypeError("timeout must be a positive number of seconds")
    return float(value)


def _retries(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError("max_retries must be a whole number, 0 or more")
    return value


def _user_agent(app_info: Optional[str]) -> str:
    parts = [f"nowgate-python/{VERSION}", f"python/{platform.python_version()}"]
    if app_info is not None:
        if not isinstance(app_info, str) or not _APP_INFO.fullmatch(app_info):
            raise TypeError("app_info must be printable ASCII, such as my-shop/1.2")
        parts.append(app_info)
    return " ".join(parts)
