"""Standalone optional Toolbox worker. Credentials travel in process environment only.

This source is shipped as a small desktop resource; xarray/Toolbox are not bundled.
The configured Python interpreter must already provide the optional Toolbox.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import math
import os
import sys
from itertools import pairwise
from typing import Any

MAX_SAMPLES = 5000


def read_dataset(request: dict[str, Any], username: str, password: str) -> dict[str, Any]:
    toolbox = importlib.import_module("copernicusmarine")
    numpy = importlib.import_module("numpy")
    dataset = toolbox.open_dataset(
        **request,
        username=username,
        password=password,
        coordinates_selection_method="strict-inside",
        vertical_axis="depth",
        raise_if_updating=True,
    )
    try:
        required = {"time", "depth", "latitude", "longitude"}
        variables = request["variables"]
        if any(set(dataset[name].dims) != required for name in variables):
            raise ValueError("Only rectilinear WGS84 time/depth grids are supported")
        if sum(dataset[name].size for name in variables) > MAX_SAMPLES:
            raise ValueError("Subset exceeds 5000 samples; narrow the request")
        # Check shape before materializing remote arrays. Never fetch an unbounded cube.
        dataset = dataset[variables].load()
        samples = []
        for name in variables:
            array = dataset[name]
            for coordinate, value in (
                array.transpose("time", "depth", "latitude", "longitude").to_series().items()
            ):
                timestamp, depth, latitude, longitude = coordinate
                timestamp_text = timestamp.isoformat()
                if timestamp.tzinfo is None:
                    timestamp_text += "Z"  # Copernicus CF time axis is UTC.
                number = float(value)
                if math.isinf(number):
                    raise ValueError("Infinite provider value")
                samples.append(
                    {
                        "variable": name,
                        "value": None if math.isnan(number) else number,
                        "unit": str(array.attrs.get("units", "")),
                        "standard_name": str(array.attrs.get("standard_name", "")),
                        "observed_at": timestamp_text,
                        "depth_m": float(depth),
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    }
                )
        resolution: dict[str, float] = {}
        for name in required:
            coordinates = dataset[name].values
            if len(coordinates) > 1:
                deltas = [
                    abs(float((b - a) / numpy.timedelta64(1, "s")))
                    if name == "time"
                    else abs(float(b - a))
                    for a, b in pairwise(coordinates)
                ]
                if deltas and all(math.isclose(value, deltas[0]) for value in deltas):
                    resolution[name] = deltas[0]
        return {
            "dataset_id": request["dataset_id"],
            "dataset_version": request["dataset_version"],
            "toolbox_version": str(getattr(toolbox, "__version__", "unknown")),
            "dataset_metadata": {
                key: str(dataset.attrs[key])
                for key in ("title", "institution", "source", "references", "history")
                if key in dataset.attrs
            },
            "coordinate_resolution": resolution,
            "samples": samples,
        }
    finally:
        dataset.close()


def main() -> None:
    try:
        request = json.load(sys.stdin)
        # Do not expose SDK stdout, exception text or credentials to the API/logs.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = read_dataset(
                request,
                os.environ["COPERNICUSMARINE_SERVICE_USERNAME"],
                os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"],
            )
        json.dump(result, sys.stdout, allow_nan=False)
    except Exception:
        print(
            '{"error":"Copernicus acquisition failed; verify credentials, '
            'dataset/version, units and subset bounds."}'
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
