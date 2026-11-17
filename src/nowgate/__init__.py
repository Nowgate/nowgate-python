"""Nowgate's Python SDK: the merchant API with safe retries, pages, exact amounts and webhook
verification, on the standard library alone.

>>> from nowgate import Nowgate
>>> client = Nowgate(api_key=os.environ["NOWGATE_API_KEY"])
>>> payment = client.payments.create(network="tron", asset="USDT", amount="25")
"""

from ._amounts import Amounts
from ._client import Nowgate
from ._core import AmountInput, APIResponse
from ._errors import (
    ApiError,
    APIConnectionError,
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    NowgateError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    SignatureFailure,
    SignatureVerificationError,
)
from ._generated.types import API_VERSION, VERSION, ErrorCode, WebhookEvent
from ._transport import Request, Response, Transport, UrllibTransport
from ._webhooks import Webhook

__version__ = VERSION

__all__ = [
    "API_VERSION",
    "VERSION",
    "Amounts",
    "AmountInput",
    "APIConnectionError",
    "ApiError",
    "APIResponse",
    "AuthenticationError",
    "ConflictError",
    "ErrorCode",
    "InvalidRequestError",
    "NotFoundError",
    "Nowgate",
    "NowgateError",
    "PermissionDeniedError",
    "RateLimitError",
    "Request",
    "Response",
    "ServerError",
    "SignatureFailure",
    "SignatureVerificationError",
    "Transport",
    "UrllibTransport",
    "Webhook",
    "WebhookEvent",
]
