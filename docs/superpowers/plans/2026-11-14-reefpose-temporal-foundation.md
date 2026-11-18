# ReefPose temporal training data

Add a development-only dataset export for training a temporal model on saved ReefPose measurements and independently frozen cycle annotations. Reuse the existing measurement tables and reference snapshots.

1. Add API tests joining a manually labeled event interval to two saved channels with an occluded measurement. Exercise deterministic output, zero-event windows, missingness, held-out rejection, and project isolation.
2. Add request/response schemas in `schemas/reefpose_temporal.py`. Build the export in `services/reefpose_temporal.py` and expose it on the existing reference router.
3. Document the API and the release conditions in `docs/roadmap/REEFVISION_1_3.md`. Validate formatting, typing, and the API tests.
