"""Retired pretrained model acquisition utility (ReefVision 1.0 policy)."""

from __future__ import annotations

import sys

MESSAGE = (
    "Pretrained model acquisition is disabled in ReefVision 1.0. "
    "Train a supported architecture or explicitly register a compatible local model. "
    "Existing models and catalogs have not been modified."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
