import type { ReefPoseSourceGrouping } from "./temporalReefPoseApi";

export function ReefPoseGroupingFields({
  grouping,
  onChange,
}: {
  grouping?: ReefPoseSourceGrouping;
  onChange: (grouping: ReefPoseSourceGrouping | undefined) => void;
}) {
  function update(key: keyof ReefPoseSourceGrouping, value: string) {
    const next = { recording_id: "", animal_id: "", ...grouping, [key]: value };
    onChange(next.recording_id || next.animal_id ? next : undefined);
  }

  return (
    <fieldset>
      <legend>Recording and animal IDs</legend>
      <p>
        Use IDs from your source records. Reuse the animal ID for recordings of
        the same animal and the recording ID for copies or clips from one
        recording.
      </p>
      <label>
        Recording ID
        <input
          maxLength={200}
          value={grouping?.recording_id ?? ""}
          onChange={(event) => update("recording_id", event.target.value)}
        />
      </label>
      <label>
        Animal ID across recordings
        <input
          maxLength={200}
          value={grouping?.animal_id ?? ""}
          onChange={(event) => update("animal_id", event.target.value)}
        />
      </label>
    </fieldset>
  );
}
