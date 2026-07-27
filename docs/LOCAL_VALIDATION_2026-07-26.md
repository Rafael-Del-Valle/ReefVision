# Local stabilization validation — 2026-07-26

Rafael ran the non-packaging release validation from the Windows checkout on
`agent/stabilize-reviewable-release` using:

```powershell
.\scripts\run-release-validation.ps1 -SkipPackaging
```

Evidence was generated beneath:

```text
.artifacts\release-validation-20260726-201002\
```

## Passing gates

- feature-freeze policy;
- Alembic upgrade/downgrade round trip;
- frontend lockfile verification;
- frontend clean installation;
- frontend TypeScript;
- frontend production build;
- Playwright Chromium installation;
- Playwright browser tests, six passed;
- Rust formatting;
- Rust cargo check;
- tracked working tree remained clean.

## Failed gates observed in that run

- bootstrap was reported failed from an npm deprecation warning written to stderr;
- repository whitespace found trailing whitespace in the short-path MSI verifier;
- Ruff reported 47 lint findings;
- Ruff formatting reported a broad formatting backlog;
- strict mypy reported 76 errors across 24 files;
- backend test collection was blocked because the experimental SAM 2 sidecar
  imported a removed `AssistMaskPrediction` symbol;
- frontend Prettier reported 16 unformatted files;
- one SAM workflow component test used a singular text query for text rendered in
  multiple places.

## Stabilization changes made after the run

- removed the trailing whitespace finding;
- contained the broken experimental SAM 2 sidecar import so it no longer prevents
  supported API routes and backend tests from starting;
- changed the SAM workflow test to accept the multiple intentional model-version
  renderings;
- kept the SAM 2 sidecar visibly unavailable with HTTP 503 until its provider
  contract is repaired and tested.

## Required rerun

Use the existing environment to avoid repeating dependency installation while the
bootstrap stderr handling is being corrected:

```powershell
.\scripts\run-release-validation.ps1 -SkipBootstrap -SkipPackaging
```

The resulting summary and failure bundle supersede this first run for the next
stabilization batch.
