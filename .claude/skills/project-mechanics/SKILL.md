---
name: project-mechanics
description: Project-specific build/test/lint/typing commands for this repo. Read this skill at the start of any phase that runs validation (`stoker-work`, `stoker-fixup`, `stoker-rebase`).
---

# Project mechanics

This file is the source of truth for how this repo runs tests, lint,
and type-checking. Profile-shipped phase skills read it at the start
of each phase and use the named commands verbatim.

## Test commands

- `focused_test`: `uv run --only-group=nox nox -s test -- tests/foo_test.py::test_bar` (pass any pytest args after `--`)
- `complete_test`: `uv run --only-group=nox nox -s test`

Test sessions start PostgreSQL and Redis via testcontainers, so
Docker (or Colima) must be running.

## Lint

- `lint_touched`: `uv run --only-group=lint prek run --files {files}`
- `lint_all`: `uv run --only-group=nox nox -s lint`

## Typing

- `typing`: `uv run --only-group=nox nox -s typing`

## Final validation

End-of-task validation runs `complete_test` + `lint_all` + `typing`
in that order, in the foreground. Coverage collection and the docs
linkcheck are CI's responsibility, not the in-iteration gate.

Extras:

- Every user-visible change needs a scriv changelog fragment in
  `changelog.d/` — verify one exists (create with
  `uv run --only-group=nox nox -s scriv-create`).
- For changes to `docs/` or substantial docstring changes, also run
  `uv run --only-group=nox nox -s docs`.

<!-- stoker-onboarded-from: github.com/lsst-sqre/rubin-stoker//profile@main
     prompt-hash: 348ec538f8f7f6fa42da3569d855eab629174668ef28ea225f8b37511daac9d4
     onboarded-at: 2026-07-10T19:06:18Z -->
