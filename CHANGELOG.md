# Changelog

All notable changes to the Python SDK (PyPI `nowgate`) are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The API's own changes are at
https://docs.nowgate.io/changelog.

## [Unreleased]

## [0.2.0] - 2026-11-20

For the API's version 2026-11-01.

### Added

- `safety_check` among a queued payout's or refund's `waiting_reason`s: Nowgate has paused payouts
  while it checks something, and the payout goes out once the check is done.
- The assets a business accepts, as one list: `accepted_assets.retrieve()` reads it and `accepted_assets.update()`
  replaces it, for every checkout page of the business at once.

### Deprecated

- `assets` on a payment link and on a plan, in a request: a link or a plan has no list of its own
  any more, and offers the assets the business accepts. The field is still taken and changes
  nothing. In an answer, `assets` is what a payer may choose now.
- `awaiting_approval` among a payout's or refund's statuses, and `approved_at`: nothing waits for
  an approval any more, so neither is seen on a new payout.

## [0.1.0] - 2026-11-17

For the API's version 2026-11-01.

### Added

- Every operation of the merchant API, typed from its spec, with webhook verification that gives
  Nowgate's own answer on every published signature vector.
- An idempotency key on every POST, the same on every attempt, and retries of what can succeed on a
  retry, after `Retry-After` or a backoff with jitter.
- Pages, and a walk over every page of a list.
- Problems as errors of their status's class, with the API's code, the fields' pointers and the
  request's ID.
- Amounts as decimal strings, numbers refused before sending, and exact helpers for an asset's
  smallest units.
- Plans, subscriptions and invoices (`plans`, `subscriptions`, `invoices`), the sandbox's
  `simulate_subscription` and `simulate_invoice`, and the `subscription.*` and `invoice.*` events.
