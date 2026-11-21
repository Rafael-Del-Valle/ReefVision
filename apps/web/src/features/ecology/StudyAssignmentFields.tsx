import type {
  EcologyStudyAssignment,
  EcologyStudyAssignmentInput,
} from "./ecologyApi";

const samplingUnitTypes = [
  ["individual", "Individual"],
  ["fragment", "Fragment"],
  ["colony", "Colony"],
  ["quadrat", "Quadrat"],
  ["transect", "Transect"],
  ["sample", "Sample"],
  ["quadrant", "Quadrant"],
] as const;

export function studyAssignmentFromForm(
  values: FormData,
): EcologyStudyAssignmentInput | null | undefined {
  const mode = values.get("studyMode");
  if (mode === "remove") return null;
  if (mode !== "review") return undefined;
  const value = (field: string) => String(values.get(field) ?? "").trim();
  return {
    tank_code: value("studyTank") || null,
    site_code: value("studySite") || null,
    treatment_code: value("studyTreatment") || null,
    sampling_unit_type:
      samplingUnitTypes.find(
        ([key]) => key === value("studySampleType"),
      )?.[0] ?? null,
    sampling_unit_id: value("studySampleID") || null,
    reviewer: value("studyReviewer"),
    notes: value("studyNotes"),
    confirm_review: values.get("studyConfirm") === "on",
  };
}

export function StudyAssignmentFields({
  assignment,
  mode,
  onMode,
}: {
  assignment?: EcologyStudyAssignment | null;
  mode: string;
  onMode: (mode: string) => void;
}) {
  return (
    <details open={mode === "review"}>
      <summary>Reviewed study assignment</summary>
      <p className="annotation-helper">
        Record where an organism was sampled and how it was assigned. Supply the
        independently assigned experimental unit above. Images and repeated
        samples stay linked to that unit.
      </p>
      <label>
        Study assignment action
        <select
          name="studyMode"
          value={mode}
          onChange={(event) => onMode(event.target.value)}
        >
          <option value="keep">
            {assignment ? "Keep reviewed assignment" : "No assignment"}
          </option>
          <option value="review">
            {assignment
              ? "Review updated assignment"
              : "Add reviewed assignment"}
          </option>
          {assignment && (
            <option value="remove">
              Remove assignment in the new revision
            </option>
          )}
        </select>
      </label>
      {mode === "review" && (
        <>
          <div className="dashboard-grid compact-grid">
            <label>
              Tank ID
              <input
                name="studyTank"
                maxLength={100}
                defaultValue={assignment?.tank_code ?? ""}
              />
            </label>
            <label>
              Site ID
              <input
                name="studySite"
                maxLength={100}
                defaultValue={assignment?.site_code ?? ""}
              />
            </label>
            <label>
              Treatment ID
              <input
                name="studyTreatment"
                maxLength={100}
                defaultValue={assignment?.treatment_code ?? ""}
              />
            </label>
            <label>
              Sampling unit type
              <select
                name="studySampleType"
                defaultValue={assignment?.sampling_unit_type ?? ""}
              >
                <option value="">Unspecified</option>
                {samplingUnitTypes.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Sampling unit ID
              <input
                name="studySampleID"
                maxLength={100}
                defaultValue={assignment?.sampling_unit_id ?? ""}
              />
            </label>
            <label>
              Study reviewer
              <input name="studyReviewer" maxLength={100} required />
            </label>
          </div>
          <label>
            Study notes
            <textarea
              name="studyNotes"
              rows={2}
              maxLength={500}
              defaultValue={assignment?.notes ?? ""}
            />
          </label>
          <label className="toggle-row">
            <input type="checkbox" name="studyConfirm" required />I reviewed
            these study assignments
          </label>
        </>
      )}
    </details>
  );
}

export function StudyAssignmentSummary({
  assignment,
}: {
  assignment: EcologyStudyAssignment;
}) {
  const values = [
    ["Tank", assignment.tank_code],
    ["Site", assignment.site_code],
    ["Treatment", assignment.treatment_code],
    [
      "Sampling unit",
      [assignment.sampling_unit_type, assignment.sampling_unit_id]
        .filter(Boolean)
        .join(" "),
    ],
    ["Reviewed by", assignment.reviewer],
  ];
  return (
    <dl>
      {values
        .filter(([, value]) => value)
        .map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
    </dl>
  );
}
