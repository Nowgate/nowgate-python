# Changelog

All notable changes to the Python SDK (PyPI `nowgate`) are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The API's own changes are at
https://docs.nowgate.io/changelog.

## [Unreleased]

### Added

- Plans, subscriptions and invoices (`plans`, `subscriptions`, `invoices`), the sandbox's
  `simulate_subscription` and `simulate_invoice`, and the `subscription.*` and `invoice.*` events.

## [0.1.0] - not yet published

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
