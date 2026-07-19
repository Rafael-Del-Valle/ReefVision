from __future__ import annotations

from pathlib import Path

from reefvision.benchmarks import (
    run_benchmark,
    summarize_benchmarks,
    synthetic_benchmark_suite,
    write_benchmark_suite,
)
from reefvision.testing.synthetic_acceptance import generate_synthetic_acceptance_dataset


def test_benchmark_runner_reports_latency_memory_and_throughput() -> None:
    counter = {"value": 0}

    def operation() -> int:
        counter["value"] += 1
        return counter["value"]

    result = run_benchmark(
        "counter",
        operation,
        iterations=3,
        warmup_iterations=1,
        throughput_amount=4,
        throughput_unit="items",
    )
    assert result.iterations == 3
    assert result.median_ms >= 0
    assert result.peak_python_bytes >= 0
    assert result.throughput_per_second is not None
    assert summarize_benchmarks([result]) == {"counter": result.median_ms}


def test_synthetic_benchmark_suite_writes_machine_readable_results(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    generate_synthetic_acceptance_dataset(fixtures)
    suite = synthetic_benchmark_suite(fixtures)
    output = tmp_path / "benchmarks.json"
    write_benchmark_suite(output, suite)

    names = {result.name for result in suite.results}
    assert "project_opening" in names
    assert "raster_editing" in names
    assert "depth_map_processing" in names
    assert "tracking_fps" in suite.skipped
    assert output.is_file()
