import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import {
  captureFieldObservation,
  type FieldClock,
  type FieldMetadata,
} from "./fieldCaptureApi";

export function FieldCaptureObservationForm({
  projectId,
  batchId,
  disabled,
}: {
  projectId: string;
  batchId: string;
  disabled: boolean;
}) {
  const queryClient = useQueryClient();
  const form = useRef<HTMLFormElement>(null);
  const [clock, setClock] = useState<FieldClock["state"]>("unknown");
  const [hasPosition, setHasPosition] = useState(false);
  const capture = useMutation({
    mutationKey: ["field-capture-upload", projectId, batchId],
    mutationFn: ({ file, metadata }: { file: File; metadata: FieldMetadata }) =>
      captureFieldObservation(projectId, batchId, file, metadata),
    onSuccess: async () => {
      form.current?.reset();
      setClock("unknown");
      setHasPosition(false);
      await queryClient.invalidateQueries({
        queryKey: ["field-batch", projectId, batchId],
      });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (capture.isPending || disabled) return;
    const data = new FormData(event.currentTarget);
    const file = data.get("file");
    if (!(file instanceof File) || !file.size) return;
    const text = (key: string) => String(data.get(key) ?? "").trim();
    const optional = (key: string) => text(key) || null;
    capture.mutate({
      file,
      metadata: {
        observer: text("observer"),
        observation_key: optional("key"),
        site: optional("site"),
        subject: optional("subject"),
        source_label: optional("source"),
        notes: optional("notes"),
        position: hasPosition
          ? {
              latitude: Number(text("latitude")),
              longitude: Number(text("longitude")),
              evidence: text("position-evidence"),
            }
          : null,
        clock: {
          state: clock,
          wall_time: optional("wall-time"),
          utc_offset_minutes:
            clock === "known_offset" ? Number(text("offset")) : null,
          evidence: text("clock-evidence"),
        },
      },
    });
  }

  return (
    <form aria-label="Capture local media" ref={form} onSubmit={submit}>
      <fieldset
        className="field-capture-grid"
        disabled={disabled || capture.isPending}
      >
        <legend>Add a field observation</legend>
        <label>
          Local media file
          <input
            type="file"
            name="file"
            required
            accept="image/*,video/*,.tif,.tiff,.mkv,.avi,.m4v,.mov"
          />
        </label>
        <label>
          Observer
          <input name="observer" required maxLength={200} />
        </label>
        <label>
          Observation key
          <input name="key" maxLength={200} />
        </label>
        <label>
          Site
          <input name="site" maxLength={200} />
        </label>
        <label>
          Subject
          <input name="subject" maxLength={200} />
        </label>
        <label>
          Source label
          <input name="source" maxLength={200} />
        </label>
        <label>
          Source clock
          <select
            aria-label="Source clock"
            value={clock}
            onChange={(event) =>
              setClock(
                event.target.value === "known_offset"
                  ? "known_offset"
                  : "unknown",
              )
            }
          >
            <option value="unknown">Unknown or unavailable</option>
            <option value="known_offset">Known UTC offset</option>
          </select>
        </label>
        <label>
          Source wall time
          <input
            name="wall-time"
            type="datetime-local"
            step={1}
            required={clock === "known_offset"}
          />
        </label>
        {clock === "known_offset" && (
          <label>
            UTC offset (minutes)
            <input
              name="offset"
              type="number"
              step={1}
              min={-840}
              max={840}
              required
            />
          </label>
        )}
        <label>
          Clock evidence
          <textarea name="clock-evidence" required maxLength={2000} rows={2} />
        </label>
        <label>
          Notes
          <textarea name="notes" maxLength={2000} rows={2} />
        </label>
        <label className="field-capture-check">
          <input
            type="checkbox"
            checked={hasPosition}
            onChange={(event) => setHasPosition(event.target.checked)}
          />{" "}
          Record coordinates
        </label>
        {hasPosition && (
          <>
            <label>
              Latitude
              <input
                name="latitude"
                type="number"
                min={-90}
                max={90}
                step="any"
                required
              />
            </label>
            <label>
              Longitude
              <input
                name="longitude"
                type="number"
                min={-180}
                max={180}
                step="any"
                required
              />
            </label>
            <label>
              Position evidence
              <input name="position-evidence" maxLength={2000} required />
            </label>
          </>
        )}
        <button type="submit">
          {capture.isPending ? "Capturing original…" : "Capture original"}
        </button>
      </fieldset>
      {capture.error && <p role="alert">{capture.error.message}</p>}
    </form>
  );
}
