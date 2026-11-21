# ReefVision 1.6 — complete frozen class-map compatibility disclosure

**Development-only; release HOLD.** Track D remains isolated on `develop/reefvision-1.6` / draft PR #77. The existing 1.0–1.5 class inventories, backend-chksummed reassignment approval, saved typed QC Workflow Builder execution, provenance and review gates were reviewed before choosing this UI approval-integrity fix.

## Researcher-visible defect

The Class Manager checked that each individual compatibility impact contained readable text and a list of reference IDs, but never reconciled that list against the protected class-reference inventory. A truncated preview could disclose a frozen dataset or registered model in `protected_records` yet silently omit or substitute its compatibility warning, while still enabling **Run reassign** or **Run Reassign and Delete**. Duplicating a compatibility category could also misrepresent which immutable maps the researcher had reviewed.

## Bounded correction

The existing execution authorization now requires a one-to-one binding for the `dataset_versions` and `model_registrations` categories. Each protected category must have exactly one matching compatibility impact, with the **same complete ordered reference IDs**; an impact may not exist without its protected inventory. Duplicate protected category keys, duplicate impact categories and repeated impact record IDs fail closed. Missing, partial, added or substituted IDs also fail closed. This is a consistency check of the displayed backend-supplied preview, not a replacement for the backend checksum, SQLite transaction or local researcher confirmation.

The Class Manager retains existing plain-language recoverable error behavior: malformed evidence disables execution and requires a fresh preview. The original datasets, model class maps, observations and histories are not modified. Existing typed standalone and twice-saved QC Workflow Builder regressions, review gates, retries and provenance remain required; an interface-only authorization check must not introduce a redundant scientific workflow node.

## Regressions and acceptance

Sixteen parameterized React scenarios (eight malformed compatibility inventories for each operation) cover missing, substituted, partial, extra, orphan, duplicate category and duplicate ID evidence. Existing valid dataset-impact / approved-operation cases remain intact. The changed functions are isolated from research data, migrations and desktop packaging.

This update **does not** close the 1.1/1.6 Alembic-0038 conflict. Full exact-head backend/frontend lint, TS, Vitest, E2E, saved scientific workflows, representative biological validation, genuine Windows MSI/CAB installation and upgrade/rollback, installed-GUI testing, and explicit owner approval remain release gates. No 1.7 or revised 1.8 code is merged into this branch.
