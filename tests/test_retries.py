"""Safe retries: an idempotency key on every POST, the same for every attempt, and retries
only of what the API says may change (api-docs-and-sdks.md section 2; ADR 0032)."""

from __future__ import annotations

import re
import time
import unittest
from email.utils import formatdate

from nowgate import (
    APIConnectionError,
    ConflictError,
    InvalidRequestError,
    RateLimitError,
    Request,
    Response,
    ServerError,
)

from .fake import PAYMENT, Fake, answer, problem, refused

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def create(fake: Fake, **options: object) -> object:
    return fake.client.payments.create(network="tron", asset="USDT", amount="25", **options)  # type: ignore[arg-type]


class Retries(unittest.TestCase):
    def test_every_post_carries_a_random_key_the_same_on_every_attempt(self) -> None:
        fake = Fake([problem(500, "internal_error"), refused(), answer(201, PAYMENT)])
        response = fake.client.with_response.payments.create(network="tron", asset="USDT", amount="25")
        self.assertEqual(response.data, PAYMENT)
        self.assertEqual(len(fake.sent), 3)
        keys = [s.headers["Idempotency-Key"] for s in fake.sent]
        self.assertRegex(keys[0], UUID)
        self.assertEqual(keys, [keys[0]] * 3)
        self.assertEqual(response.idempotency_key, keys[0])
        self.assertEqual(len({s.body for s in fake.sent}), 1)

    def test_each_call_gets_its_own_key_and_the_callers_is_used_as_given(self) -> None:
        fake = Fake([answer(201, PAYMENT)] * 3)
        create(fake)
        create(fake)
        create(fake, idempotency_key="order-1042")
        keys = [s.headers["Idempotency-Key"] for s in fake.sent]
        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(keys[2], "order-1042")
        with self.assertRaisesRegex(TypeError, "idempotency_key must be a non-empty string"):
            create(fake, idempotency_key="")

    def test_get_put_patch_and_delete_carry_no_key_and_are_retried_alike(self) -> None:
        fake = Fake(
            [
                problem(503, "pool_exhausted"),
                answer(200, PAYMENT),
                problem(502, "http_502"),
                answer(200, {"rules": []}),
                refused(),
                answer(200, {"id": "plink_1"}),
                problem(504, "http_504"),
                answer(200, {"id": "dst_1"}),
            ]
        )
        fake.client.payments.retrieve("pay_1")
        fake.client.forwarding.update(rules=[])
        fake.client.payment_links.update("plink_1", title="T-shirt")
        fake.client.payout_destinations.disable("dst_1")
        methods = [s.method for s in fake.sent]
        self.assertEqual(methods, ["GET", "GET", "PUT", "PUT", "PATCH", "PATCH", "DELETE", "DELETE"])
        self.assertTrue(all("Idempotency-Key" not in s.headers for s in fake.sent))

    def test_no_answer_is_retried_then_is_a_connection_error_with_its_cause(self) -> None:
        fake = Fake([refused(), refused(), refused()])
        with self.assertRaises(APIConnectionError) as caught:
            create(fake)
        self.assertRegex(
            str(caught.exception),
            r"Couldn't reach Nowgate at https://sandbox-api.nowgate.io/v1: .*Connection refused",
        )
        self.assertIsInstance(caught.exception.__cause__, ConnectionRefusedError)
        self.assertEqual(len(fake.sent), 3)
        self.assertEqual(fake.waits, [0.5, 1.0])

    def test_an_attempt_that_times_out_is_retried_then_is_a_connection_error(self) -> None:
        def hang(request: Request) -> Response:
            raise TimeoutError("timed out")

        fake = Fake([hang, answer(200, PAYMENT)], timeout=0.02)
        self.assertEqual(fake.client.payments.retrieve("pay_1"), PAYMENT)
        self.assertEqual(fake.sent[0].timeout, 0.02)

        slow = Fake([hang, hang], timeout=0.02, max_retries=1)
        with self.assertRaisesRegex(APIConnectionError, "didn't answer within 0.02 s"):
            slow.client.payments.retrieve("pay_1")

    def test_409_in_progress_is_retried_after_its_retry_after_other_conflicts_arent(self) -> None:
        fake = Fake(
            [
                problem(409, "idempotency_key_in_progress", {"retry-after": "1"}),
                answer(201, PAYMENT),
                problem(409, "payout_not_cancelable"),
            ]
        )
        create(fake)
        self.assertEqual(fake.waits, [1.0])
        with self.assertRaises(ConflictError):
            fake.client.payouts.cancel("po_1")
        self.assertEqual(len(fake.sent), 3)

    def test_429_is_retried_after_its_retry_after_in_seconds_or_as_a_date_or_with_backoff(self) -> None:
        soon = formatdate(time.time() + 3, usegmt=True)
        fake = Fake(
            [
                problem(429, "rate_limited", {"retry-after": "2"}),
                problem(429, "rate_limited", {"retry-after": soon}),
                answer(200, PAYMENT),
                problem(429, "rate_limited"),
                answer(200, PAYMENT),
            ]
        )
        fake.client.payments.retrieve("pay_1")
        fake.client.payments.retrieve("pay_1")
        self.assertEqual(fake.waits[0], 2.0)
        self.assertIn(fake.waits[1], (2.0, 3.0, 4.0))
        self.assertEqual(fake.waits[2], 0.5)

    def test_a_retry_after_over_60_seconds_isnt_waited_for(self) -> None:
        fake = Fake([problem(429, "rate_limited", {"retry-after": "61"})])
        with self.assertRaises(RateLimitError) as caught:
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(caught.exception.retry_after, 61)
        self.assertEqual(fake.waits, [])

    def test_500_502_503_and_504_are_retried_501_isnt(self) -> None:
        for status in (500, 502, 503, 504):
            fake = Fake([problem(status, "internal_error"), answer(200, PAYMENT)])
            self.assertEqual(fake.client.payments.retrieve("pay_1"), PAYMENT)
        fake = Fake([problem(501, "internal_error")])
        with self.assertRaises(ServerError):
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(len(fake.sent), 1)

    def test_other_4xx_arent_retried_idempotency_key_reused_among_them(self) -> None:
        for status, code in (
            (400, "invalid_request"),
            (401, "invalid_api_key"),
            (403, "insufficient_scope"),
            (404, "not_found"),
            (422, "idempotency_key_reused"),
        ):
            fake = Fake([problem(status, code)])
            with self.assertRaises(Exception) as caught:
                create(fake)
            self.assertEqual(getattr(caught.exception, "code"), code)
            self.assertEqual(len(fake.sent), 1)
        fake = Fake([problem(422, "idempotency_key_reused")])
        with self.assertRaises(InvalidRequestError):
            create(fake)

    def test_two_retries_by_default_per_client_and_per_call(self) -> None:
        fake = Fake([problem(503, "pool_exhausted")] * 3)
        with self.assertRaises(ServerError):
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(len(fake.sent), 3)

        none = Fake([problem(503, "pool_exhausted")], max_retries=0)
        with self.assertRaises(ServerError):
            none.client.payments.retrieve("pay_1")
        self.assertEqual(len(none.sent), 1)

        per_call = Fake([problem(503, "pool_exhausted")] * 5)
        with self.assertRaises(ServerError):
            per_call.client.payments.retrieve("pay_1", max_retries=4)
        self.assertEqual(len(per_call.sent), 5)

    def test_backoff_doubles_from_half_a_second_up_to_8_seconds_each_a_random_fraction(self) -> None:
        fake = Fake([refused()] * 7, max_retries=6)
        with self.assertRaises(APIConnectionError):
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(fake.waits, [0.5, 1.0, 2.0, 4.0, 8.0, 8.0])

        half = Fake([refused(), answer(200, PAYMENT)], random=0.5)
        half.client.payments.retrieve("pay_1")
        self.assertEqual(half.waits, [0.25])

    def test_with_response_gives_the_status_headers_request_id_and_idempotency_facts(self) -> None:
        fake = Fake(
            [answer(200, PAYMENT, {"X-Request-Id": "req_1", "Idempotent-Replayed": "true"})]
        )
        response = fake.client.with_response.payments.create(
            network="tron", asset="USDT", amount="25", idempotency_key="order-1"
        )
        self.assertEqual(response.data, PAYMENT)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["x-request-id"], "req_1")
        self.assertEqual(response.request_id, "req_1")
        self.assertEqual(response.idempotency_key, "order-1")
        self.assertTrue(response.idempotent_replayed)

        get = Fake([answer(200, PAYMENT)])
        retrieved = get.client.with_response.payments.retrieve("pay_1")
        self.assertIsNone(retrieved.idempotency_key)
        self.assertFalse(retrieved.idempotent_replayed)
        self.assertIsNone(retrieved.request_id)


if __name__ == "__main__":
    unittest.main()
