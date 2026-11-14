"""Run the synthetic ReefPose-S engineering benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "api"))

from reefvision.ml.reefpose.benchmark import BenchmarkConfig, run_benchmark  # noqa: E402
from reefvision.ml.reefpose.model import ReefPoseConfig  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark ReefPose-S with synthetic tensors (not biological validation)."
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument("--input-size", type=int, default=256)
    parser.add_argument("--keypoints", type=int, default=8)
    parser.add_argument("--base-channels", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--inference-iterations", type=int, default=100)
    parser.add_argument("--training-steps", type=int, default=50)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--no-amp", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_benchmark(
        BenchmarkConfig(
            model=ReefPoseConfig(
                num_keypoints=args.keypoints,
                input_height=args.input_size,
                input_width=args.input_size,
                base_channels=args.base_channels,
            ),
            device=args.device,
            batch_size=args.batch_size,
            warmup_iterations=args.warmup,
            inference_iterations=args.inference_iterations,
            training_steps=args.training_steps,
            amp=not args.no_amp,
            seed=args.seed,
        )
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
