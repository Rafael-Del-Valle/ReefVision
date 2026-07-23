import { FormEvent, useEffect, useMemo, useState } from "react";

import { getApiBaseUrl } from "../../runtime";

interface StoragePathState {
  key: "data_dir" | "model_cache_dir" | "temp_dir";
  label: string;
  description: string;
  active_path: string;
  pending_path: string;
  exists: boolean;
  writable: boolean;
  free_bytes: number | null;
  restart_required: boolean;
  environment_variable: string;
  environment_locked: boolean;
}

interface StorageSettingsResponse {
  settings_file: string;
  restart_required: boolean;
  paths: StoragePathState[];
  notes: string[];
}

type StorageForm = Record<StoragePathState["key"], string>;

function bytesLabel(bytes: number | null): string {
  if (bytes === null) return "Unavailable";
  if (bytes >= 1_099_511_627_776) {
    return `${(bytes / 1_099_511_627_776).toFixed(2)} TiB`;
  }
  if (bytes >= 1_073_741_824) {
    return `${(bytes / 1_073_741_824).toFixed(2)} GiB`;
  }
  if (bytes >= 1_048_576) {
    return `${(bytes / 1_048_576).toFixed(1)} MiB`;
  }
  return `${Math.round(bytes / 1024)} KiB`;
}

function formFromResponse(response: StorageSettingsResponse): StorageForm {
  const values: StorageForm = {
    data_dir: "",
    model_cache_dir: "",
    temp_dir: "",
  };
  for (const path of response.paths) values[path.key] = path.pending_path;
  return values;
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // Keep the HTTP fallback when an error response is not JSON.
  }
  return `Request failed with HTTP ${response.status}`;
}

async function getStorageSettings(): Promise<StorageSettingsResponse> {
  const response = await fetch(`${getApiBaseUrl()}/system/storage-settings`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as StorageSettingsResponse;
}

async function saveStorageSettings(
  values: StorageForm,
  acknowledgeRestart: boolean,
): Promise<StorageSettingsResponse> {
  const response = await fetch(`${getApiBaseUrl()}/system/storage-settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...values,
      acknowledge_restart: acknowledgeRestart,
    }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as StorageSettingsResponse;
}

export function StorageSettingsOverlay() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<StorageSettingsResponse | null>(null);
  const [values, setValues] = useState<StorageForm>({
    data_dir: "",
    model_cache_dir: "",
    temp_dir: "",
  });
  const [acknowledgeRestart, setAcknowledgeRestart] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(null);
    void getStorageSettings()
      .then((response) => {
        if (!active) return;
        setSettings(response);
        setValues(formFromResponse(response));
        setAcknowledgeRestart(false);
        setSaved(false);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(
          caught instanceof Error
            ? caught.message
            : "Storage settings could not be loaded.",
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  const changed = useMemo(
    () =>
      settings?.paths.some(
        (path) => values[path.key] !== path.active_path,
      ) ?? false,
    [settings, values],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const response = await saveStorageSettings(values, acknowledgeRestart);
      setSettings(response);
      setValues(formFromResponse(response));
      setSaved(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Storage settings could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="secondary"
        onClick={() => setOpen(true)}
        style={{ position: "fixed", right: 24, bottom: 24, zIndex: 30 }}
      >
        Storage settings
      </button>

      {open && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="storage-settings-title"
            style={{ maxWidth: 860, maxHeight: "90vh", overflowY: "auto" }}
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">External drives and disk usage</p>
                <h2 id="storage-settings-title">Storage settings</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>

            {loading && <p>Loading storage locations...</p>}
            {error && <p className="form-error">{error}</p>}

            {settings && !loading && (
              <form className="system-form" onSubmit={submit}>
                {settings.paths.map((path) => (
                  <section className="system-card" key={path.key}>
                    <div className="section-heading">
                      <div>
                        <h3>{path.label}</h3>
                        <p>{path.description}</p>
                      </div>
                      <span className="status-chip">
                        {path.writable
                          ? `${bytesLabel(path.free_bytes)} free`
                          : "Unavailable"}
                      </span>
                    </div>
                    <label>
                      Directory
                      <input
                        value={values[path.key]}
                        disabled={path.environment_locked}
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            [path.key]: event.target.value,
                          }))
                        }
                        placeholder={
                          path.key === "data_dir"
                            ? "E:\\ReefVision\\data"
                            : "E:\\ReefVision\\cache"
                        }
                      />
                    </label>
                    <small>
                      Active now: <code>{path.active_path}</code>
                    </small>
                    {path.environment_locked && (
                      <p>
                        Controlled by <code>{path.environment_variable}</code>.
                        Remove that environment variable before editing this
                        field.
                      </p>
                    )}
                  </section>
                ))}

                <section className="system-card">
                  <h3>Before saving</h3>
                  <ul className="system-details">
                    {settings.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                  <label className="toggle-row">
                    <input
                      type="checkbox"
                      checked={acknowledgeRestart}
                      onChange={(event) =>
                        setAcknowledgeRestart(event.target.checked)
                      }
                    />
                    I understand ReefVision must restart and existing project
                    data is not moved automatically.
                  </label>
                  <p>
                    Preferences file: <code>{settings.settings_file}</code>
                  </p>
                </section>

                <div className="modal-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={saving || (changed && !acknowledgeRestart)}
                  >
                    {saving ? "Saving..." : "Save directories"}
                  </button>
                </div>
                {saved && (
                  <p>
                    Storage settings saved. Restart ReefVision to activate the
                    pending paths.
                  </p>
                )}
              </form>
            )}
          </section>
        </div>
      )}
    </>
  );
}
