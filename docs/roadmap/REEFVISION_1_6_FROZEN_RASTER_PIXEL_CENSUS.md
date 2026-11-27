# ReefVision 1.6 — frozen raster pixel census

2026-11-27. Isolated draft PR #77; issue #76. The original 1.0.3 and 1.6
managed raster producer (`storage/masks.py`) uses Pillow grayscale getbbox
and a nonzero-pixel histogram, returning integer pixel edges as floats.
The existing frozen 0007 QC guard checked that area fit the entire source
image, not the recorded bounding rectangle. Fractional raster edges or an
area larger than its bounding rectangle could thus survive re-signing both
the image snapshot and manifest.

Require whole-pixel raster edges (both integral JSON numbers and integral
floats remain compatible) and a positive integer area no larger than the
bounding rectangle in source pixels squared. Polygon geometry and 0006
detection-only snapshots are unchanged. Do not infer new measurements or
open or modify user mask files: this is an internal consistency constraint,
not verification of the recorded PNG content digest.

Seven synthetic regression cases (five corrupt, two valid) and two new
database-backed standalone QC, manual regeneration and saved executable
Workflow Builder configurations cover rejection, rollback, replay and the
pending researcher-review gate. Independent Pillow exercise: all 511
nonempty binary 3 x 3 masks with integer and float coordinates (1,022
positive cases), 1,022 impossible-area variants and four fractional-edge
variants passed the isolated geometry check. Full repository test execution
and final exact-head CI are not claimed; local git checkout is blocked by
DNS. No new workflow node or migration is needed.

Release HOLD: independent 1.1/1.6 Alembic lineage reconciliation, full CI,
representative biological workflows, physical installed Windows MSI/CAB
clean install/upgrade/rollback and GUI qualification, researcher approval.

## Exact-head CI correction (2026-11-27)

Actions run 45966890248 passed frontend and native Windows preservation;
backend pytest reported 3,017 passed, 32 skipped, and one failed positive
raster fixture. Its box (2, 3, 6, 7) is 4 x 4, not 4 x 5; 20 nonzero
pixels cannot fit. Correct the valid full-box case to 16 and the invalid
boundary case to 17. Independent Pillow checks generated sparse 12-pixel
and full 16-pixel masks with exactly these bounds and verified their
histogram counts. Production QC, saved Workflow Builder regression paths,
review requirements and source data are unchanged. Replacement exact-head
CI and installed Windows qualification remain required.
