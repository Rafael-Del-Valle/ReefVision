import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TuningTrial } from "../../api/client";
import {
  bestFitnessSoFar,
  rankedTrials,
  TuningDashboard,
} from "./TuningDashboard";

const trials: TuningTrial[] = [0.1, 0.12, 0.11, 0.15, 0.14].map(
  (fitness, index) => ({
    trial_number: index + 1,
    status: "completed",
    fitness,
    metrics: { "metrics/mAP50-95(B)": fitness },
    hyperparameters: { lr0: 0.001 * (index + 1) },
    duration_seconds: 4,
    epoch_history: [],
    artifacts: [],
    native_values: {},
  }),
);

describe("TuningDashboard", () => {
  it("derives monotonic best-so-far values in chronological order", () => {
    expect(bestFitnessSoFar(trials)).toEqual([0.1, 0.12, 0.12, 0.15, 0.15]);
  });

  it("ranks valid trials while preserving deterministic trial identity", () => {
    const failed = {
      ...trials[0],
      trial_number: 8,
      status: "failed",
      fitness: 0.9,
    };
    expect(
      rankedTrials([...trials, failed]).map((trial) => trial.trial_number),
    ).toEqual([4, 5, 2, 3, 1]);
  });

  it("shows fitness provenance, rankings, and the best trial inspector", () => {
    render(
      <TuningDashboard
        results={{
          fitness_definition: "Recorded provider fitness",
          search_space: {},
          max_trials: 10,
          epochs_per_trial: 5,
          patience: 3,
          trials,
          best_trial_number: 4,
          best_hyperparameters: { lr0: 0.004 },
        }}
      />,
    );
    expect(screen.getByText("Fitness vs Trial")).toBeInTheDocument();
    expect(
      screen.getByText("Best Fitness So Far vs Trial"),
    ).toBeInTheDocument();
    expect(screen.getByText("Recorded provider fitness")).toBeInTheDocument();
    expect(screen.getByLabelText("Trial 4 inspector")).toBeInTheDocument();
  });
});
