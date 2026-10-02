"""External pose interoperability contracts."""

from __future__ import annotations

from typing import Literal

PoseInteroperabilityFormat = Literal[
    "slp",
    "nwb",
    "coco",
    "dlc_csv",
    "ultralytics_pose",
]
