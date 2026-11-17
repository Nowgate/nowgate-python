"""Webhook verification gives the engine's answers: the 21 published vectors, and the edge
cases the engine's own tests pin (api-docs-and-sdks.md section 1.7)."""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from nowgate import NowgateError, SignatureVerificationError, Webhook

from .fake import fixture


def read(path: str) -> Dict[str, Any]:
    with open(fixture(path), encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    return data


PUBLISHED = read("api/webhooks/signature-vectors.json")
EDGES = read("sdks/testdata/signature-edge-cases.json")
VALID = PUBLISHED["vectors"][0]
assert VALID["valid"], "the first published vector must be valid"


def outcome(run: Callable[[], object]) -> str:
    try:
        run()
    except SignatureVerificationError as err:
        return err.reason
    return "valid"


def is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


class Vectors(unittest.TestCase):
    def test_verify_signature_gives_the_engines_answer_on_every_vector(self) -> None:
        for name, file, least in (("published", PUBLISHED, 21), ("edge cases", EDGES, 20)):
            self.assertGreaterEqual(len(file["vectors"]), least)
            for v in file["vectors"]:
                with self.subTest(file=name, vector=v["name"]):
                    got = outcome(
                        lambda: Webhook.verify_signature(
                            v["body"], v["header"], v["secrets"], tolerance=file["tolerance_seconds"], now=v["now"]
                        )
                    )
                    self.assertEqual(got, "valid" if v["valid"] else v["error"])

    def test_construct_event_gives_the_same_answers_from_bytes_too(self) -> None:
        for name, file in (("published", PUBLISHED), ("edge cases", EDGES)):
            for v in file["vectors"]:
                with self.subTest(file=name, vector=v["name"]):
                    at = datetime.fromtimestamp(v["now"], tz=timezone.utc)
                    try:
                        got = outcome(lambda: Webhook.construct_event(v["body"].encode(), v["header"], v["secrets"], now=at))
                    except NowgateError:
                        got = "valid, not JSON"
                    want = ("valid" if is_json(v["body"]) else "valid, not JSON") if v["valid"] else v["error"]
                    self.assertEqual(got, want)


class Verification(unittest.TestCase):
    def test_construct_event_returns_the_event(self) -> None:
        event = Webhook.construct_event(VALID["body"], VALID["header"], VALID["secrets"][0], now=VALID["now"])
        self.assertEqual(event["object"], "event")
        self.assertEqual(event["type"], "payment.finished")
        self.assertEqual(event["data"]["object"]["object"], "payment")

    def test_the_body_may_be_text_or_bytes_and_the_header_a_list(self) -> None:
        raw = VALID["body"].encode()
        for body in (VALID["body"], raw, bytearray(raw), memoryview(raw)):
            Webhook.verify_signature(body, VALID["header"], VALID["secrets"], now=VALID["now"])
        t, v1 = VALID["header"].split(",")
        Webhook.verify_signature(VALID["body"], [t, v1], VALID["secrets"], now=VALID["now"])
        Webhook.verify_signature(VALID["body"], (t, v1), tuple(VALID["secrets"]), now=VALID["now"])
        self.assertEqual(outcome(lambda: Webhook.verify_signature(VALID["body"], None, VALID["secrets"], now=VALID["now"])), "malformed")

    def test_the_tolerance_and_the_time_are_the_callers_to_set(self) -> None:
        match = re.match(r"t=(\d+),", VALID["header"])
        assert match is not None
        signed_at = int(match.group(1))
        late = signed_at + 3600
        self.assertEqual(outcome(lambda: Webhook.verify_signature(VALID["body"], VALID["header"], VALID["secrets"], now=late)), "timestamp")
        Webhook.verify_signature(VALID["body"], VALID["header"], VALID["secrets"], tolerance=3600, now=late)
        with self.assertRaises(SignatureVerificationError):
            Webhook.verify_signature(VALID["body"], VALID["header"], VALID["secrets"], now=signed_at + 301)
        self.assertEqual(
            outcome(lambda: Webhook.verify_signature(VALID["body"], VALID["header"], VALID["secrets"])),
            "timestamp",
            "now is the clock by default, long after the vector",
        )

    def test_arguments_the_verifier_cant_use_are_type_errors_not_failures(self) -> None:
        v: Any = Webhook.verify_signature
        for secrets in ("", [], [""], [VALID["secrets"][0], 7], None, b"whsec_x"):
            with self.subTest(secrets=secrets), self.assertRaises(TypeError):
                v(VALID["body"], VALID["header"], secrets, now=VALID["now"])
        with self.assertRaisesRegex(TypeError, "exactly as received"):
            v({"id": "evt"}, VALID["header"], VALID["secrets"], now=VALID["now"])
        with self.assertRaisesRegex(TypeError, "now must be"):
            v(VALID["body"], VALID["header"], VALID["secrets"], now=float("nan"))
        with self.assertRaisesRegex(TypeError, "tolerance"):
            v(VALID["body"], VALID["header"], VALID["secrets"], tolerance=-1, now=VALID["now"])
        with self.assertRaisesRegex(TypeError, "header must be"):
            v(VALID["body"], 7, VALID["secrets"], now=VALID["now"])

    def test_the_failure_says_why_with_the_vectors_names(self) -> None:
        with self.assertRaises(SignatureVerificationError) as caught:
            Webhook.verify_signature(VALID["body"] + " ", VALID["header"], VALID["secrets"], now=VALID["now"])
        self.assertEqual(caught.exception.reason, "mismatch")
        self.assertEqual(str(caught.exception), "mismatch: no signature matches the body with any of the secrets")


if __name__ == "__main__":
    unittest.main()
