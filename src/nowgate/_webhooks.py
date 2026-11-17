"""Webhook signatures, verified exactly as the engine's webhooks/signing.Verify does. The
published vectors in api/webhooks/signature-vectors.json pin the format:
Nowgate-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from datetime import datetime
from typing import List, Optional, Sequence, Tuple, Union, cast

from ._errors import NowgateError, SignatureFailure, SignatureVerificationError
from ._generated.types import WebhookEvent

Payload = Union[str, bytes, bytearray, memoryview]
"""The body exactly as received, before any JSON parsing: its bytes, or its text."""

DEFAULT_TOLERANCE = 300
_INT64_MAX = 2**63 - 1
# Go's strings.TrimSpace trims Unicode's White_Space characters, these; Python's own
# str.strip() trims more (the separators U+001C to U+001F).
_SPACE = "\t\n\v\f\r \u0085                 　"
_TIMESTAMP = re.compile(r"[+-]?[0-9]+")
_SIGNATURE = re.compile(r"[0-9a-fA-F]{64}")


class Webhook:
    """Webhook verification. It needs no client, since a webhook handler often has none."""

    @staticmethod
    def verify_signature(
        payload: Payload,
        header: Union[str, Sequence[str], None],
        secrets: Union[str, Sequence[str]],
        tolerance: float = DEFAULT_TOLERANCE,
        now: Union[float, datetime, None] = None,
    ) -> None:
        """Checks a webhook's Nowgate-Signature header against its raw body. It returns
        when the signature's time is within tolerance seconds of now and any v1 signature
        matches any of the secrets (two while you rotate), and raises a
        SignatureVerificationError otherwise. Every comparison takes the same time."""
        keys = _secret_list(secrets)
        body = _bytes(payload)
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
        ):
            raise TypeError("tolerance must be a number of seconds, 0 or more")
        at = _seconds(now)
        parsed = _parse(_header_text(header))
        if isinstance(parsed, str):
            raise SignatureVerificationError(cast(SignatureFailure, parsed))
        timestamp, signatures = parsed
        age = at - timestamp
        if age > tolerance or age < -tolerance:
            raise SignatureVerificationError("timestamp")

        message = f"{timestamp}.".encode("ascii") + body
        ok = False
        for secret in keys:
            mac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
            for signature in signatures:
                ok = hmac.compare_digest(mac, signature) or ok  # no early exit
        if not ok:
            raise SignatureVerificationError("mismatch")

    @staticmethod
    def construct_event(
        payload: Payload,
        header: Union[str, Sequence[str], None],
        secrets: Union[str, Sequence[str]],
        tolerance: float = DEFAULT_TOLERANCE,
        now: Union[float, datetime, None] = None,
    ) -> WebhookEvent:
        """Checks a webhook's signature as verify_signature does, then returns its event,
        told apart by its type: payment.*, payout.*, refund.*, destination.* or batch.*."""
        Webhook.verify_signature(payload, header, secrets, tolerance, now)
        try:
            event = json.loads(_bytes(payload).decode("utf-8"))
        except ValueError as err:
            raise NowgateError("The webhook's signature verified, but its body isn't JSON") from err
        return cast(WebhookEvent, event)


def _parse(header: str) -> Union[Tuple[int, List[bytes]], str]:
    """The header read as signing.parse reads it, or why it can't be."""
    timestamp: Optional[int] = None
    signatures: List[bytes] = []
    for part in header.split(","):
        item = part.strip(_SPACE)
        key, eq, value = item.partition("=")
        if not eq:
            return "malformed"
        if key == "t":
            # strconv.ParseInt(value, 10, 64): an optional sign, ASCII digits, within int64.
            if timestamp is not None or not _TIMESTAMP.fullmatch(value):
                return "malformed"
            n = int(value)
            if n <= 0 or n > _INT64_MAX:
                return "malformed"
            timestamp = n
        elif key == "v1":
            if not _SIGNATURE.fullmatch(value):
                return "malformed"
            signatures.append(bytes.fromhex(value))
        # other schemes are ignored, so new ones can be added
    if timestamp is None:
        return "malformed"
    if not signatures:
        return "no_signature"
    return timestamp, signatures


def _header_text(header: Union[str, Sequence[str], None]) -> str:
    if header is None:
        return ""
    if isinstance(header, str):
        return header
    if isinstance(header, (list, tuple)) and all(isinstance(h, str) for h in header):
        return ",".join(header)
    raise TypeError("header must be the Nowgate-Signature header: a string, or a list of them")


def _secret_list(secrets: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(secrets, str):
        keys = [secrets]
    elif isinstance(secrets, (list, tuple)):
        keys = list(secrets)
    else:
        keys = []
    if not keys or any(not isinstance(s, str) or s == "" for s in keys):
        raise TypeError(
            "secrets must be your endpoint's secret (whsec_...), or a list of them while you rotate"
        )
    return keys


def _bytes(payload: Payload) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    raise TypeError("Pass the body exactly as received, its bytes or text, before any JSON parsing")


def _seconds(now: Union[float, datetime, None]) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return now.timestamp()
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise TypeError("now must be a datetime or a number of Unix seconds")
    return float(now)
