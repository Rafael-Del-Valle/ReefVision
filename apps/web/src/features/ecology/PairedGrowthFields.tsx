import type { EcologyAnalysis } from "./ecologyAnalysisApi";
import type { PairedGrowthDesign } from "./pairedGrowthContrastApi";

export type PairedGrowthDraft = Omit<
  PairedGrowthDesign,
  "missingness_policy"
> & { missingness_policy: "" | "complete_unit" };
export const emptyPairedGrowthDraft: PairedGrowthDraft = {
  baseline_date: "",
  followup_date: "",
  experimental_unit_type: "",
  estimand: "",
  missingness_policy: "",
};

export function pairedVisitDates(analysis: EcologyAnalysis) {
  const selection = analysis.snapshot.selection;
  const plan = selection.kind === "growth" ? selection.sampling_plan : null;
  return (
    plan?.[0]?.dates
      .filter((day) => plan.every((unit) => unit.dates.includes(day)))
      .sort() ?? []
  );
}

export function pairedDesignReady(draft: PairedGrowthDraft) {
  return Boolean(
    draft.baseline_date &&
    draft.followup_date > draft.baseline_date &&
    draft.experimental_unit_type.trim() &&
    draft.estimand.trim().length >= 3 &&
    draft.missingness_policy === "complete_unit",
  );
}

export function PairedGrowthFields({
  dates,
  value,
  onChange,
}: {
  dates: readonly string[];
  value: PairedGrowthDraft;
  onChange: (draft: PairedGrowthDraft) => void;
}) {
  const update = (delta: Partial<PairedGrowthDraft>) =>
    onChange({ ...value, ...delta });
  return (
    <>
      <p>
        Compare follow-up minus baseline. Within each unit, matched organisms
        sharing a parent colony are averaged first. Each colony or ungrouped
        organism receives equal weight within that unit. Each complete unit
        contributes one difference.
      </p>
      <label>
        Baseline UTC date
        <select
          required
          value={value.baseline_date}
          onChange={(event) => update({ baseline_date: event.target.value })}
        >
          <option value="">Select a planned date</option>
          {dates.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
      </label>
      <label>
        Follow-up UTC date
        <select
          required
          value={value.followup_date}
          onChange={(event) => update({ followup_date: event.target.value })}
        >
          <option value="">Select a later planned date</option>
          {dates.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
      </label>
      {value.baseline_date &&
        value.followup_date &&
        value.followup_date <= value.baseline_date && (
          <p role="status">Choose a follow-up date later than the baseline.</p>
        )}
      <label>
        Independent unit type
        <input
          value={value.experimental_unit_type}
          onChange={(event) =>
            update({ experimental_unit_type: event.target.value })
          }
          maxLength={150}
          placeholder="e.g. tank"
          required
        />
      </label>
      <label>
        Declared estimand
        <textarea
          value={value.estimand}
          onChange={(event) => update({ estimand: event.target.value })}
          minLength={3}
          maxLength={1500}
          required
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={value.missingness_policy === "complete_unit"}
          onChange={(event) =>
            update({
              missingness_policy: event.target.checked ? "complete_unit" : "",
            })
          }
        />
        Exclude a unit when any planned organism lacks a matched measurement at
        either visit.
      </label>
    </>
  );
}
