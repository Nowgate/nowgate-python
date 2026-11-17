"""The client: keys and environments, what every request carries, bodies, paths and
queries, and the key never shown (api-docs-and-sdks.md sections 1.2 and 1.3)."""

from __future__ import annotations

import json
import platform
import unittest
from typing import Any

from nowgate import VERSION, AuthenticationError, Nowgate, NowgateError, Response

from .fake import KEY, PAYMENT, SECRET, Fake, answer, problem


class Keys(unittest.TestCase):
    def test_the_base_url_follows_the_keys_environment(self) -> None:
        self.assertEqual(Nowgate(f"ngk_live_{SECRET}").base_url, "https://api.nowgate.io/v1")
        self.assertEqual(Nowgate(KEY).base_url, "https://sandbox-api.nowgate.io/v1")
        given = Nowgate(KEY, base_url="https://sandbox.example.com/v1/")
        self.assertEqual(given.base_url, "https://sandbox.example.com/v1")

    def test_other_environments_need_a_base_url_and_live_keys_go_only_over_https(self) -> None:
        with self.assertRaisesRegex(TypeError, "A test key needs a base_url"):
            Nowgate(f"ngk_test_{SECRET}")
        local = Nowgate(f"ngk_test_{SECRET}", base_url="http://127.0.0.1:8080/v1")
        self.assertEqual(local.base_url, "http://127.0.0.1:8080/v1")
        for env in ("live", "sandbox"):
            with self.assertRaisesRegex(TypeError, f"A {env} key is sent only over https"):
                Nowgate(f"ngk_{env}_{SECRET}", base_url="http://api.example.com/v1")
        for base in ("ftp://example.com/v1", "example.com", "https://x/v1?a=1", "https://x/v1#f"):
            with self.assertRaises(TypeError):
                Nowgate(KEY, base_url=base)

    def test_a_key_that_isnt_a_nowgate_key_is_refused_before_any_request_without_showing_it(
        self,
    ) -> None:
        for key in (f"sk_live_{SECRET}", "ngk_sandbox_", f"ngk_Live_{SECRET}", f"ngk_sandbox_{SECRET} "):
            with self.assertRaises(TypeError) as caught:
                Nowgate(key)
            self.assertNotIn(SECRET, str(caught.exception))
        with self.assertRaises(TypeError):
            Nowgate(None)  # type: ignore[arg-type]

    def test_options_are_checked_when_the_client_is_made(self) -> None:
        bad: list[dict[str, Any]] = [
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": float("inf")},
            {"timeout": True},
            {"max_retries": -1},
            {"max_retries": 1.5},
            {"max_retries": False},
            {"app_info": "my shop\n"},
            {"app_info": "café/1"},
            {"transport": "urllib"},
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(TypeError):
                Nowgate(KEY, **options)


class Requests(unittest.TestCase):
    def test_every_request_carries_the_key_user_agent_and_accept_public_ones_too(self) -> None:
        fake = Fake([answer(200, {"object": "status"})], app_info="my-shop/1.2")
        fake.client.status.retrieve()
        sent = fake.sent[0]
        self.assertEqual(sent.method, "GET")
        self.assertEqual(sent.url, "https://sandbox-api.nowgate.io/v1/status")
        self.assertEqual(sent.headers["Authorization"], f"Bearer {KEY}")
        self.assertEqual(sent.headers["Accept"], "application/json")
        self.assertEqual(
            sent.headers["User-Agent"],
            f"nowgate-python/{VERSION} python/{platform.python_version()} my-shop/1.2",
        )
        self.assertIsNone(sent.body)
        self.assertNotIn("Content-Type", sent.headers)
        self.assertEqual(sent.timeout, 60.0)

    def test_a_body_is_json_path_ids_are_encoded_and_query_parameters_sent_as_given(self) -> None:
        fake = Fake([answer(201, PAYMENT), answer(200, PAYMENT), answer(200, {"data": []})])
        fake.client.payments.create(
            network="tron", asset="USDT", amount="25", metadata={"order": "1042 ü"}
        )
        self.assertEqual(fake.sent[0].headers["Content-Type"], "application/json")
        self.assertEqual(
            fake.sent[0].body,
            '{"network":"tron","asset":"USDT","amount":"25","metadata":{"order":"1042 ü"}}'.encode(),
        )
        fake.client.payments.retrieve("pay_1/../x?y")
        self.assertEqual(fake.sent[1].url, "https://sandbox-api.nowgate.io/v1/payments/pay_1%2F..%2Fx%3Fy")
        fake.client.payments.list(limit=2, status="finished", order_id="a&b=c")
        self.assertEqual(
            fake.sent[2].url,
            "https://sandbox-api.nowgate.io/v1/payments?limit=2&status=finished&order_id=a%26b%3Dc",
        )

    def test_a_body_without_fields_is_sent_as_an_empty_object_a_post_without_a_body_has_none(
        self,
    ) -> None:
        fake = Fake([answer(201, {"id": "rf_1"}), answer(200, {"id": "po_1"})])
        fake.client.refunds.create("pay_1")
        self.assertEqual(fake.sent[0].body, b"{}")
        fake.client.payouts.cancel("po_1")
        self.assertIsNone(fake.sent[1].body)
        self.assertIn("Idempotency-Key", fake.sent[1].headers)

    def test_an_empty_or_missing_id_is_refused_before_sending(self) -> None:
        fake = Fake([])
        with self.assertRaisesRegex(TypeError, "id must be a non-empty string"):
            fake.client.payments.retrieve("")
        with self.assertRaises(TypeError):
            fake.client.payments.retrieve(None)  # type: ignore[arg-type]
        self.assertEqual(fake.sent, [])

    def test_the_key_is_never_shown(self) -> None:
        fake = Fake([problem(401, "invalid_api_key")])
        shown = [repr(fake.client), str(fake.client), repr(fake.client._requester), repr(vars(fake.client))]
        shown += [repr(vars(fake.client._requester)), repr(fake.client.payments.__dict__)]
        with self.assertRaises(AuthenticationError) as caught:
            fake.client.payments.retrieve("pay_1")
        shown += [str(caught.exception), repr(caught.exception), repr(vars(caught.exception))]
        for text in shown:
            self.assertNotIn(SECRET, text)
        self.assertIn("ngk_sandbox_012345…9abc", repr(fake.client))

    def test_a_transport_of_the_callers_own_is_used_for_every_request(self) -> None:
        seen = []

        def transport(request: Any) -> Response:
            seen.append(request.url)
            return answer(200, PAYMENT)

        client = Nowgate(KEY, transport=transport)
        client.payments.retrieve("pay_1")
        client.with_response.payments.retrieve("pay_2")
        self.assertEqual(len(seen), 2)

    def test_a_success_that_isnt_json_is_an_error_not_retried(self) -> None:
        fake = Fake([Response(status=200, headers={"content-type": "text/html"}, body=b"<html>")])
        with self.assertRaisesRegex(NowgateError, "Nowgate answered 200 with a body that isn't JSON"):
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(len(fake.sent), 1)
        empty = Fake([Response(status=204, headers={})])
        self.assertIsNone(empty.client.payment_links.retrieve("plink_1"))

    def test_bodies_given_by_the_caller_are_never_changed(self) -> None:
        items = [{"network": "tron", "asset": "USDT", "amount": 5}]
        fake = Fake([answer(201, {"id": "pob_1"})])
        fake.client.payout_batches.create(items=items)  # type: ignore[arg-type]
        self.assertEqual(items[0]["amount"], 5)
        self.assertEqual(json.loads(fake.sent[0].body or b"")["items"][0]["amount"], "5")


if __name__ == "__main__":
    unittest.main()
