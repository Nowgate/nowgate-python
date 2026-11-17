"""The generated surface: the versions, and every operation as a method in both families
(api-docs-and-sdks.md sections 1.2 and 4)."""

from __future__ import annotations

import json
import re
import unittest

import nowgate
from nowgate import API_VERSION, VERSION, Nowgate

from .fake import KEY, SDK, fixture


def snake(name: str) -> str:
    return re.sub(r"[A-Z]", lambda m: "_" + m.group(0).lower(), name)


class Surface(unittest.TestCase):
    def test_the_versions_are_the_specs_and_the_packages(self) -> None:
        spec = fixture("api/openapi.yaml").read_text(encoding="utf-8")
        info = re.search(r"^info:\n(?:  .*\n)*?  version: ['\"]?([0-9-]+)['\"]?$", spec, re.MULTILINE)
        assert info is not None
        self.assertEqual(API_VERSION, info.group(1))
        project = (SDK / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'\nversion = "{VERSION}"\n', project)
        self.assertEqual(nowgate.__version__, VERSION)

    def test_every_named_operation_is_a_method_in_both_families(self) -> None:
        names = json.loads(fixture("sdks/operations.json").read_text(encoding="utf-8"))
        client = Nowgate(KEY)
        for operation, name in names["operations"].items():
            resource, method = (snake(part) for part in name.split("."))
            with self.subTest(operation=operation):
                self.assertTrue(callable(getattr(getattr(client, resource), method)))
                self.assertTrue(callable(getattr(getattr(client.with_response, resource), method)))
        self.assertTrue(callable(client.payments.list_all))
        self.assertFalse(hasattr(client.with_response.payments, "list_all"))

    def test_the_public_names(self) -> None:
        for name in nowgate.__all__:
            self.assertTrue(hasattr(nowgate, name), name)
        from nowgate import types

        for name in ("Payment", "CreatePaymentRequest", "PaymentStatus", "ErrorCode", "WebhookEvent"):
            self.assertIn(name, types.__all__)


if __name__ == "__main__":
    unittest.main()
