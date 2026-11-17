"""Pages: list returns one page as the API sends it, and list_all walks every page by
starting_after while has_more (api-docs-and-sdks.md section 1.4)."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from urllib.parse import urlsplit

from nowgate import NotFoundError, Response

from .fake import Fake, answer, problem


def item(n: int) -> Dict[str, Any]:
    return {"id": f"pay_{n}", "object": "payment"}


def page(ids: List[int], has_more: bool) -> Response:
    return answer(200, {"object": "list", "data": [item(n) for n in ids], "has_more": has_more})


def queries(fake: Fake) -> List[str]:
    return [urlsplit(s.url).query for s in fake.sent]


class Pages(unittest.TestCase):
    def test_list_returns_one_page_exactly_as_the_api_sends_it(self) -> None:
        fake = Fake([page([5, 4], True)])
        listed = fake.client.payments.list(limit=2, starting_after="pay_6")
        self.assertEqual(listed, {"object": "list", "data": [item(5), item(4)], "has_more": True})
        self.assertEqual(fake.sent[0].url, "https://sandbox-api.nowgate.io/v1/payments?limit=2&starting_after=pay_6")

    def test_list_all_fetches_pages_of_100_as_its_iterated_following_starting_after(self) -> None:
        fake = Fake([page([5, 4], True), page([3, 2], True), page([1], False)])
        walk = fake.client.payments.list_all(status="finished")
        self.assertEqual(fake.sent, [], "nothing is fetched before the walk starts")
        self.assertEqual([p["id"] for p in walk], ["pay_5", "pay_4", "pay_3", "pay_2", "pay_1"])
        self.assertEqual(
            queries(fake),
            [
                "limit=100&status=finished",
                "limit=100&starting_after=pay_4&status=finished",
                "limit=100&starting_after=pay_2&status=finished",
            ],
        )

    def test_list_all_keeps_the_callers_limit_and_starting_point_and_stops_early(self) -> None:
        fake = Fake([page([5, 4], True), page([3, 2], True)])
        ids = []
        for refund in fake.client.refunds.list_all(limit=2, starting_after="pay_6"):
            ids.append(refund["id"])
            if len(ids) == 3:
                break
        self.assertEqual(ids, ["pay_5", "pay_4", "pay_3"])
        self.assertEqual(queries(fake), ["limit=2&starting_after=pay_6", "limit=2&starting_after=pay_4"])

    def test_list_all_stops_on_an_empty_page_and_takes_no_ending_before(self) -> None:
        fake = Fake([page([], True)])
        self.assertEqual(list(fake.client.payouts.list_all()), [])
        self.assertEqual(len(fake.sent), 1)
        with self.assertRaises(TypeError):
            fake.client.payouts.list_all(ending_before="po_1")  # type: ignore[call-arg]
        with self.assertRaisesRegex(TypeError, "not ending_before"):
            fake.client._requester.paginate("/payouts", query={"ending_before": "po_1"})

    def test_each_page_is_retried_as_any_get_and_a_failure_ends_the_walk(self) -> None:
        fake = Fake([page([2], True), problem(503, "pool_exhausted"), page([1], False), problem(404, "not_found")])
        self.assertEqual([link["id"] for link in fake.client.payment_links.list_all()], ["pay_2", "pay_1"])
        self.assertEqual(len(fake.sent), 3)
        with self.assertRaises(NotFoundError):
            for _ in fake.client.payout_batches.list_all():
                pass  # the first page fails


if __name__ == "__main__":
    unittest.main()
