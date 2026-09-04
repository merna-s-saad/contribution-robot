# DEPENDENCIES

updated-at: 2026-09-04

## Runtime

| Package | Version | Why | Notes |
|---|---|---|---|
| `requests` | `>=2.31.0` | the single GraphQL POST in `fetch_calendar` | **Lazily imported.** Fixture runs and the whole test suite work without it; the import failure is caught and reported as a clear error. |

Nothing else. Standard library only: `argparse`, `json`, `os`, `random`, `sys`,
`collections.abc`, `dataclasses`, `datetime`, `pathlib`, `typing`,
`xml.sax.saxutils`.

Python 3.13 in use. Floor is effectively **3.10** (PEP 604 `X | None`, and
`list[...]` generics under `from __future__ import annotations`). Note the test
suite uses `itertools.pairwise`, which is **3.10+**.

## Development

| Tool | Why |
|---|---|
| `pytest` | test suite |
| `ruff` | lint; a repo hook blocks on failure |
| Google Chrome (headless) | manual render verification only, not required to build |

## External services

**GitHub GraphQL API** — `https://api.github.com/graphql`, querying
`user.contributionsCollection.contributionCalendar`.

- Requires a token; the calendar is not available unauthenticated.
- Scope needed: `read:user` (classic PAT).
- Passed as `--token` or `$GITHUB_TOKEN`.
- 30s timeout, no retries.
- Rate limit is 5000 points/hour for a PAT; this query costs 1. Not a concern.
- Every live run caches the raw payload to `<out-dir>/last_fetch.json`, which
  doubles as the fixture format.

## Upgrade notes

The GraphQL query is small and stable; the fields used (`date`,
`contributionCount`, `weekday`, `totalContributions`) have been in the public
schema for years. `extract_weeks` unwraps the response defensively and will
raise a readable error rather than a `KeyError` if the shape changes.
