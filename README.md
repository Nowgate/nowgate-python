# Nowgate for Python

Nowgate's SDK for its merchant API: payments, payment links, payouts and refunds, with webhook
verification. It needs Python 3.10 or later and nothing outside the standard library, and it is
fully typed: every result is a `TypedDict`, checked by mypy and your editor.

```bash
pip install nowgate
```

## Create a payment

```python
import os

from nowgate import Nowgate

client = Nowgate(api_key=os.environ["NOWGATE_API_KEY"])

payment = client.payments.create(
    network="tron",
    asset="USDT",
    amount="25.00",
    order_id="1042",
    idempotency_key="order-1042",
)
print(payment["id"], payment["deposit"]["address"], payment["amount"])
```

The key picks the API: an `ngk_sandbox_…` key reaches the sandbox and an `ngk_live_…` key the
live API. Amounts are decimal strings (or `Decimal`s), never floats. A failed call is retried
safely with its idempotency key, and lists page with `list_all`.

## Verify a webhook

```python
from nowgate import SignatureVerificationError, Webhook

# body: the request's raw body, exactly as received; signature: its Nowgate-Signature header.
try:
    event = Webhook.construct_event(body, signature, os.environ["NOWGATE_WEBHOOK_SECRET"])
except SignatureVerificationError:
    ...  # answer 400
```

## Documentation

The guides and the API reference are at [docs.nowgate.io](https://docs.nowgate.io), and this
SDK's page is [docs.nowgate.io/sdks/python](https://docs.nowgate.io/sdks/python). The
[changelog](https://docs.nowgate.io/changelog) lists its releases, each with the API version it
was made for.
