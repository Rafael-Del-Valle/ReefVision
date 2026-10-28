import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorState } from "../../components/ui/AsyncState";
import { calculateLunarContext, type LunarPhase } from "./lunarContextApi";

const PHASE_LABELS: Record<LunarPhase, string> = {
  new_moon: "New moon",
  waxing_crescent: "Waxing crescent",
  first_quarter: "First quarter",
  waxing_gibbous: "Waxing gibbous",
  full_moon: "Full moon",
  waning_gibbous: "Waning gibbous",
  last_quarter: "Last quarter",
  waning_crescent: "Waning crescent",
};

// Require an explicit UTC timestamp; do not silently interpret local time.
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

export function LunarContextPanel({ projectId }: { projectId: string }) {
  const [observedAt, setObservedAt] = useState("");
  const [inputError, setInputError] = useState("");

  const lunar = useMutation({
    mutationFn: () => calculateLunarContext(projectId, observedAt.trim()),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const timestamp = observedAt.trim();
    const parsedTimestamp = Date.parse(timestamp);
    if (
      !UTC_TIMESTAMP.test(timestamp) ||
      !Number.isFinite(parsedTimestamp) ||
      new Date(parsedTimestamp).toISOString().slice(0, 19) !==
        timestamp.slice(0, 19)
    ) {
      setInputError("Enter a valid UTC timestamp including seconds and Z.");
      return;
    }
    setInputError("");
    lunar.mutate();
  }

  const result = lunar.data;

  return (
    <section className="panel-card training-content" aria-label="Lunar context">
      <div className="section-heading">
        <div>
          <h3>Lunar context (offline)</h3>
          <p>
            Estimate geocentric moon phase from an explicit observation time.
            This is not a tidal prediction or a local sky ephemeris.
          </p>
        </div>
      </div>

      <form onSubmit={submit}>
        <label>
          Observation time (UTC)
          <input
            type="text"
            required
            placeholder="2026-10-28T18:00:00Z"
            value={observedAt}
            onChange={(event) => {
              setObservedAt(event.target.value);
              setInputError("");
              lunar.reset();
            }}
          />
        </label>
        <p className="form-help">
          Use ISO 8601 UTC with seconds and Z. ReefVision will not guess the
          observation time from upload time or your computer clock.
        </p>
        <button type="submit" disabled={lunar.isPending}>
          {lunar.isPending ? "Calculating…" : "Calculate lunar phase"}
        </button>
      </form>

      {inputError && <p role="alert">{inputError}</p>}
      {lunar.error && (
        <ErrorState
          title="Lunar calculation failed"
          message={lunar.error.message}
        />
      )}
      {result && (
        <section aria-label="Lunar calculation results">
          <h4>Phase: {PHASE_LABELS[result.phase]}</h4>
          <p>
            Approximate illumination:{" "}
            {(result.illuminated_fraction * 100).toFixed(1)}%
          </p>
          <p>
            Mean-synodic lunar age estimate:{" "}
            {result.approximate_lunar_age_days.toFixed(2)} days
          </p>
          <p>Observation time: {result.observed_at}</p>
          <details>
            <summary>Calculation provenance and scientific limits</summary>
            <p>
              Algorithm: <code>{result.algorithm}</code>
            </p>
            <p>
              Content SHA-256: <code>{result.content_sha256}</code>
            </p>
            <p>
              Reference frame: {result.reference_frame}
            </p>
            <ul>
              {result.methodological_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </section>
  );
}
