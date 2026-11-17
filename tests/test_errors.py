"""Problems as errors of their status's class, carrying the whole problem (api-docs-and-sdks.md
section 1.5)."""

from __future__ import annotations

import unittest
from typing import List, Tuple, Type

from nowgate import (
    APIConnectionError,
    ApiError,
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    NowgateError,
    PermissionDeniedError,
    RateLimitError,
    Response,
    ServerError,
    SignatureVerificationError,
)
from nowgate.types import FieldError

from .fake import Fake, answer, problem


class Errors(unittest.TestCase):
    def test_a_problem_carries_every_field_its_pointers_and_the_docs_page(self) -> None:
        fields: List[FieldError] = [
            {"pointer": "/amount", "code": "amount_too_precise", "detail": "USDT has 6 decimals."},
            {"pointer": "/items/2/amount", "code": "amount_invalid", "detail": "Not a decimal."},
        ]
        fake = Fake(
            [
                problem(
                    422,
                    "amount_too_precise",
                    {"Retry-After": "5", "X-Request-Id": "req_h"},
                    errors=fields,
                )
            ]
        )
        with self.assertRaises(InvalidRequestError) as caught:
            fake.client.payments.create(network="tron", asset="USDT", amount="1.0000001")
        err = caught.exception
        self.assertIsInstance(err, ApiError)
        self.assertIsInstance(err, NowgateError)
        self.assertEqual(err.status, 422)
        self.assertEqual(err.code, "amount_too_precise")
        self.assertEqual(err.title, "Problem")
        self.assertEqual(err.detail, "The amount_too_precise detail.")
        self.assertEqual(err.type, "https://docs.nowgate.io/errors/amount_too_precise")
        self.assertEqual(err.instance, "/v1/payments")
        self.assertEqual(err.request_id, "req_problem")
        self.assertEqual(err.retry_after, 5)
        self.assertEqual(err.errors, fields)
        self.assertEqual(err.headers["x-request-id"], "req_h")
        self.assertEqual(
            str(err),
            "amount_too_precise: The amount_too_precise detail. "
            "(https://docs.nowgate.io/errors/amount_too_precise)",
        )

    def test_each_status_has_its_class(self) -> None:
        classes: List[Tuple[int, Type[ApiError]]] = [
            (400, InvalidRequestError),
            (401, AuthenticationError),
            (403, PermissionDeniedError),
            (404, NotFoundError),
            (405, InvalidRequestError),
            (409, ConflictError),
            (413, InvalidRequestError),
            (414, InvalidRequestError),
            (415, InvalidRequestError),
            (422, InvalidRequestError),
            (429, RateLimitError),
            (500, ServerError),
            (501, ServerError),
            (503, ServerError),
            (418, ApiError),
        ]
        for status, error_class in classes:
            fake = Fake([problem(status, "some_code")], max_retries=0)
            with self.subTest(status=status), self.assertRaises(ApiError) as caught:
                fake.client.payments.retrieve("pay_1")
            self.assertIs(type(caught.exception), error_class)
            self.assertEqual(caught.exception.status, status)

    def test_an_answer_that_isnt_a_problem_is_its_statuss_error_with_the_first_500_bytes(self) -> None:
        page = "<html><body>x" + "é" * 400 + "</body></html>"
        fake = Fake(
            [
                Response(
                    status=502,
                    reason="Bad Gateway",
                    headers={"content-type": "text/html", "x-request-id": "req_proxy"},
                    body=page.encode(),
                )
            ],
            max_retries=0,
        )
        with self.assertRaises(ServerError) as caught:
            fake.client.payments.retrieve("pay_1")
        err = caught.exception
        self.assertEqual(err.code, "http_502")
        self.assertEqual(err.title, "Bad Gateway")
        self.assertIsNone(err.type)
        self.assertEqual(err.request_id, "req_proxy")
        detail = err.detail or ""
        self.assertTrue(detail.startswith("<html><body>xéé"))
        self.assertEqual(len(detail.encode()), 499)
        self.assertNotIn("�", detail)
        self.assertRegex(str(err), "^http_502: <html>")

    def test_json_that_isnt_a_problem_and_an_empty_answer_fall_back_the_same_way(self) -> None:
        fake = Fake(
            [
                Response(status=404, headers={"content-type": "application/json"}, body=b'{"error":"nope"}'),
                Response(status=403, headers={}),
                answer(400, ["code", "title"]),
            ],
            max_retries=0,
        )
        with self.assertRaises(NotFoundError) as not_found:
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(not_found.exception.code, "http_404")
        self.assertEqual(not_found.exception.detail, '{"error":"nope"}')
        with self.assertRaises(PermissionDeniedError) as denied:
            fake.client.payments.retrieve("pay_1")
        self.assertIsNone(denied.exception.detail)
        self.assertEqual(str(denied.exception), "http_403: HTTP 403")
        with self.assertRaises(InvalidRequestError) as listed:
            fake.client.payments.retrieve("pay_1")
        self.assertEqual(listed.exception.code, "http_400")

    def test_the_errors_without_an_answer_are_nowgate_errors_not_api_errors(self) -> None:
        failure = SignatureVerificationError("mismatch")
        self.assertIsInstance(failure, NowgateError)
        self.assertNotIsInstance(failure, ApiError)
        self.assertEqual(failure.reason, "mismatch")
        connection = APIConnectionError("no answer")
        self.assertIsInstance(connection, NowgateError)
        self.assertNotIsInstance(connection, ApiError)
        self.assertNotIsInstance(connection, ConnectionError)
        self.assertFalse(issubclass(PermissionDeniedError, PermissionError))


if __name__ == "__main__":
    unittest.main()
