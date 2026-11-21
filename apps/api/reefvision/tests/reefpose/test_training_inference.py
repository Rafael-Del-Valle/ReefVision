from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import torch
from PIL import Image
from torch import nn

from reefvision.ml.reefpose.checkpoints import load_checkpoint, save_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseCancelledError, ReefPoseValidationError
from reefvision.ml.reefpose.inference import ReefPosePredictor
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseOutput, ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition
from reefvision.ml.reefpose.training import ReefPoseTrainer, ReefPoseTrainingConfig


def _schema(count: int = 2) -> AnatomySchema:
    return AnatomySchema(
        schema_id="schema-1",
        name="Synthetic anatomy",
        revision=1,
        landmarks=tuple(
            LandmarkDefinition(landmark_id=f"point-{index}", name=f"point-{index}")
            for index in range(count)
        ),
    )


def _batch(count: int = 2) -> dict[str, torch.Tensor]:
    heatmaps = torch.zeros(2, count, 16, 16)
    heatmaps[:, :, 8, 8] = 1.0
    return {
        "image": torch.rand(2, 3, 64, 64),
        "heatmaps": heatmaps,
        "heatmap_weights": torch.ones(2, count),
        "visibility_targets": torch.ones(2, count),
    }


class CheckpointAndTrainingTests(unittest.TestCase):
    def test_historical_v1_checkpoint_hashes_load_and_match_expected_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            for historical in (True, False):
                with self.subTest(historical=historical):
                    path = root / f"v1-{historical}.pt"
                    save_checkpoint(path, model=model, schema=_schema(), epoch=0, global_step=0)
                    payload = torch.load(path, map_location="cpu", weights_only=True)
                    anatomy = payload["anatomy_schema"]
                    anatomy["schema_version"] = "reefpose-anatomy-0001"
                    if historical:
                        for landmark in anatomy["landmarks"]:
                            landmark.pop("symmetric_with", None)
                            landmark.pop("required", None)
                    anatomy.pop("integrity_hash")
                    v1_hash = hashlib.sha256(
                        json.dumps(
                            anatomy,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest()
                    anatomy["integrity_hash"] = v1_hash
                    payload["anatomy_integrity_hash"] = v1_hash
                    torch.save(payload, path)

                    state = load_checkpoint(
                        path,
                        device="cpu",
                        expected_schema_hash=v1_hash,
                    )

                    self.assertEqual(state.schema.schema_id, "schema-1")
                    self.assertEqual(state.schema.SCHEMA_VERSION, "reefpose-anatomy-0002")

    def test_historical_v1_hash_cannot_authorize_added_anatomy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            path = root / "historical-v1.pt"
            save_checkpoint(path, model=model, schema=_schema(), epoch=0, global_step=0)
            payload = torch.load(path, map_location="cpu", weights_only=True)
            anatomy = payload["anatomy_schema"]
            anatomy["schema_version"] = "reefpose-anatomy-0001"
            for landmark in anatomy["landmarks"]:
                landmark.pop("symmetric_with", None)
                landmark.pop("required", None)
            anatomy.pop("integrity_hash")
            historical_hash = hashlib.sha256(
                json.dumps(
                    anatomy,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            anatomy["integrity_hash"] = historical_hash
            payload["anatomy_integrity_hash"] = historical_hash

            for mutation in ("required", "symmetry"):
                with self.subTest(mutation=mutation):
                    changed = dict(payload)
                    changed_anatomy = {
                        **anatomy,
                        "landmarks": [dict(item) for item in anatomy["landmarks"]],
                    }
                    if mutation == "required":
                        changed_anatomy["landmarks"][0]["required"] = False
                    else:
                        changed_anatomy["landmarks"][0]["symmetric_with"] = "point-1"
                        changed_anatomy["landmarks"][1]["symmetric_with"] = "point-0"
                    changed["anatomy_schema"] = changed_anatomy
                    torch.save(changed, path)

                    with self.assertRaisesRegex(
                        ReefPoseValidationError,
                        "integrity hash",
                    ):
                        load_checkpoint(
                            path,
                            device="cpu",
                            expected_schema_hash=historical_hash,
                        )

    def test_checkpoint_round_trip_restores_schema_model_and_optimizer_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "checkpoint.pt"
            schema = _schema()
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

            save_checkpoint(
                path,
                model=model,
                schema=schema,
                epoch=3,
                global_step=17,
                metrics={"loss": 0.25},
                optimizer=optimizer,
                training_config={"epochs": 4},
                reproducibility={"seed": 9, "torch_version": torch.__version__},
            )
            state = load_checkpoint(path, device="cpu")

            self.assertEqual(state.epoch, 3)
            self.assertEqual(state.global_step, 17)
            self.assertEqual(state.schema, schema)
            self.assertEqual(state.model.config.num_keypoints, 2)
            self.assertIsNotNone(state.optimizer_state)
            self.assertIs(type(state.reproducibility["torch_version"]), str)
            for expected, actual in zip(model.parameters(), state.model.parameters(), strict=True):
                torch.testing.assert_close(actual, expected)

    def test_tampered_checkpoint_schema_fails_integrity_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "checkpoint.pt"
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            save_checkpoint(path, model=model, schema=_schema(), epoch=0, global_step=0)
            payload = torch.load(path, map_location="cpu", weights_only=True)
            payload["anatomy_schema"]["name"] = "Tampered"
            torch.save(payload, path)

            with self.assertRaisesRegex(ReefPoseValidationError, "integrity"):
                load_checkpoint(path, device="cpu")

    def test_cpu_training_updates_weights_logs_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            schema = _schema()
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            before = next(model.parameters()).detach().clone()
            trainer = ReefPoseTrainer(
                model,
                schema,
                ReefPoseTrainingConfig(
                    epochs=1,
                    learning_rate=1e-3,
                    device="cpu",
                    amp=True,
                    output_dir=output,
                    seed=123,
                ),
            )

            first = trainer.fit([_batch()])

            self.assertFalse(torch.equal(before, next(model.parameters()).detach()))
            self.assertEqual(first.completed_epochs, 1)
            self.assertEqual(first.global_step, 1)
            self.assertTrue(first.last_checkpoint.is_file())
            rows = [
                json.loads(line) for line in (output / "training.jsonl").read_text().splitlines()
            ]
            self.assertEqual(rows[0]["epoch"], 0)
            self.assertEqual(rows[0]["device"], "cpu")
            self.assertFalse(rows[0]["amp_enabled"])

            resumed_model = ReefPoseS(model.config)
            resumed = ReefPoseTrainer(
                resumed_model,
                schema,
                ReefPoseTrainingConfig(
                    epochs=2,
                    learning_rate=1e-3,
                    device="cpu",
                    output_dir=output / "resumed",
                    seed=123,
                ),
            ).fit([_batch()], resume_from=first.last_checkpoint)
            self.assertEqual(resumed.completed_epochs, 2)
            self.assertEqual(resumed.global_step, 2)

    def test_cancellation_saves_recoverable_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            trainer = ReefPoseTrainer(
                model,
                _schema(),
                ReefPoseTrainingConfig(epochs=2, device="cpu", output_dir=output),
            )

            with self.assertRaises(ReefPoseCancelledError):
                trainer.fit([_batch()], cancellation_check=lambda: True)
            cancelled = output / "cancelled.pt"
            self.assertTrue(cancelled.is_file())
            state = load_checkpoint(cancelled, device="cpu")
            self.assertEqual(state.epoch, -1)
            self.assertEqual(state.global_step, 0)

            resumed = ReefPoseTrainer(
                ReefPoseS(model.config),
                _schema(),
                ReefPoseTrainingConfig(
                    epochs=1,
                    device="cpu",
                    output_dir=output / "resumed",
                ),
            ).fit([_batch()], resume_from=cancelled)
            self.assertEqual(resumed.completed_epochs, 1)
            self.assertEqual(resumed.global_step, 1)

    def test_epoch_callback_reports_completed_epoch_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            reported: list[tuple[int, int, dict[str, float]]] = []
            trainer = ReefPoseTrainer(
                ReefPoseS(
                    ReefPoseConfig(
                        num_keypoints=2,
                        input_height=64,
                        input_width=64,
                        base_channels=8,
                    )
                ),
                _schema(),
                ReefPoseTrainingConfig(epochs=1, device="cpu", output_dir=Path(raw)),
            )

            trainer.fit(
                [_batch()],
                epoch_callback=lambda epoch, total, metrics: reported.append(
                    (epoch, total, dict(metrics))
                ),
            )

            self.assertEqual(len(reported), 1)
            self.assertEqual(reported[0][0:2], (1, 1))
            self.assertIn("selection_loss", reported[0][2])

    def test_mid_epoch_cancellation_records_completed_optimizer_steps(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            model = ReefPoseS(
                ReefPoseConfig(
                    num_keypoints=2,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                )
            )
            trainer = ReefPoseTrainer(
                model,
                _schema(),
                ReefPoseTrainingConfig(epochs=1, device="cpu", output_dir=output),
            )
            checks = iter((False, True))

            with self.assertRaises(ReefPoseCancelledError):
                trainer.fit([_batch(), _batch()], cancellation_check=lambda: next(checks))

            state = load_checkpoint(output / "cancelled.pt", device="cpu")
            self.assertEqual(state.epoch, -1)
            self.assertEqual(state.global_step, 1)

    def test_resume_preserves_historical_best_checkpoint_in_new_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = root / "original"
            original.mkdir()
            config = ReefPoseConfig(
                num_keypoints=2,
                input_height=64,
                input_width=64,
                base_channels=8,
            )
            model = ReefPoseS(config)
            schema = _schema()
            save_checkpoint(
                original / "best.pt",
                model=model,
                schema=schema,
                epoch=0,
                global_step=1,
                metrics={"selection_loss": 0.0, "best_selection_loss": 0.0},
            )
            save_checkpoint(
                original / "last.pt",
                model=model,
                schema=schema,
                epoch=0,
                global_step=1,
                metrics={"selection_loss": 0.4, "best_selection_loss": 0.0},
            )

            result = ReefPoseTrainer(
                ReefPoseS(config),
                schema,
                ReefPoseTrainingConfig(
                    epochs=2,
                    device="cpu",
                    output_dir=root / "resumed",
                ),
            ).fit([_batch()], resume_from=original / "last.pt")

            best = load_checkpoint(result.best_checkpoint, device="cpu")
            self.assertEqual(best.metrics["selection_loss"], 0.0)
            self.assertEqual(best.metrics["best_selection_loss"], 0.0)


class _FixedPoseModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = ReefPoseConfig(
            num_keypoints=2,
            input_height=64,
            input_width=64,
            base_channels=8,
        )

    def forward(self, inputs: torch.Tensor) -> ReefPoseOutput:
        heatmaps = torch.full((inputs.shape[0], 2, 16, 16), -10.0, device=inputs.device)
        heatmaps[:, 0, 8, 8] = 10.0
        heatmaps[:, 1, 4, 12] = 10.0
        visibility = torch.tensor([[10.0, -10.0]], device=inputs.device).repeat(inputs.shape[0], 1)
        return ReefPoseOutput(heatmaps=heatmaps, visibility_logits=visibility)


class InferenceTests(unittest.TestCase):
    def test_prediction_restores_source_coordinates_and_confidence(self) -> None:
        predictor = ReefPosePredictor(_FixedPoseModel(), _schema(), device="cpu")
        image = Image.new("RGB", (100, 50), color=(120, 100, 80))

        prediction = predictor.predict(image)

        self.assertEqual(len(prediction.landmarks), 2)
        self.assertAlmostEqual(prediction.landmarks[0].x, 50.0, places=5)
        self.assertAlmostEqual(prediction.landmarks[0].y, 25.0, places=5)
        self.assertGreater(prediction.landmarks[0].confidence, 0.99)
        self.assertEqual(prediction.landmarks[0].visibility_state, "visible")
        self.assertLess(prediction.landmarks[1].confidence, 0.001)
        self.assertEqual(prediction.landmarks[1].visibility_state, "absent")
        self.assertGreaterEqual(prediction.confidence, 0.0)
        self.assertLessEqual(prediction.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
