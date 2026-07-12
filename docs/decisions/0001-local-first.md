# ADR 0001: Local-first application

## Status

Accepted.

## Decision

ReefVision will run locally and keep the initial research workflow independent
of hosted accounts or cloud services.

## Consequences

- The application must provide explicit backup and recovery workflows.
- Local file paths and Windows behavior are first-class concerns.
- Multi-user authentication and real-time collaboration are outside version 0.1.
