import { useMutation } from "@tanstack/react-query";
import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useRef, useState } from "react";

import { request } from "../../api/client";

interface OfflineMediaReport {
  status: "verified" | "incomplete";
  version: string;
  installer: string;
  source_commit: string;
  manifest_sha256: string;
  total_verified_bytes: number;
  files: {
    name: string;
    status: "matched" | "changed" | "missing" | "unexpected" | "unreadable";
  }[];
}

export function OfflineUpdatePanel({
  focusRequest,
}: {
  focusRequest?: number;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [directory, setDirectory] = useState("");
  const [pin, setPin] = useState("");
  const [pickerError, setPickerError] = useState("");
  const verification = useMutation({
    mutationFn: () =>
      request<OfflineMediaReport>(
        "/system/updates/inspect",
        {
          method: "POST",
          body: JSON.stringify({
            directory: directory.trim(),
            manifest_sha256: pin.trim(),
          }),
        },
        15 * 60_000,
      ),
  });
  useEffect(() => {
    if (focusRequest) heading.current?.focus();
  }, [focusRequest]);
  function selectFolder(value: string) {
    setDirectory(value);
    setPickerError("");
    verification.reset();
  }
  async function browse() {
    try {
      const chosen = await open({
        directory: true,
        multiple: false,
        title: "Choose ReefVision installation media",
      });
      if (typeof chosen === "string") selectFolder(chosen);
    } catch {
      setPickerError("Enter the full path to the local installer folder.");
    }
  }
  const report = verification.data;
  return (
    <section className="system-card" aria-labelledby="offline-updates-heading">
      <h3 id="offline-updates-heading" tabIndex={-1} ref={heading}>
        Offline updates and recovery
      </h3>
      <p>
        Choose the folder containing the MSI, all cabinets and
        build-provenance.json. Enter the manifest SHA-256 from the candidate
        review.
      </p>
      <form
        className="system-form"
        onSubmit={(event) => {
          event.preventDefault();
          verification.mutate();
        }}
      >
        <label>
          Installer folder
          <input
            value={directory}
            onChange={(event) => selectFolder(event.target.value)}
            disabled={verification.isPending}
            required
          />
        </label>
        {isTauri() && (
          <button
            type="button"
            className="secondary"
            onClick={browse}
            disabled={verification.isPending}
          >
            Browse folders
          </button>
        )}
        <label>
          Expected manifest SHA-256
          <input
            value={pin}
            onChange={(event) => {
              setPin(event.target.value);
              verification.reset();
            }}
            spellCheck={false}
            autoComplete="off"
            disabled={verification.isPending}
            required
          />
        </label>
        <button
          type="submit"
          disabled={
            verification.isPending ||
            !directory.trim() ||
            !/^[a-f0-9]{64}$/i.test(pin.trim())
          }
        >
          {verification.isPending ? "Verifying media…" : "Verify offline media"}
        </button>
      </form>
      {pickerError && <p role="alert">{pickerError}</p>}
      {verification.error && (
        <p className="form-error" role="alert">
          {verification.error.message}
        </p>
      )}
      {report && (
        <div aria-live="polite">
          <h4>
            {report.status === "verified"
              ? "Media checksums verified"
              : "Media needs attention"}
          </h4>
          <p>
            ReefVision {report.version} · source{" "}
            <code>{report.source_commit}</code>
          </p>
          <ul>
            {report.files.map((file) => (
              <li key={file.name}>
                <code>{file.name}</code> — {file.status}
              </li>
            ))}
          </ul>
          {report.status === "verified" ? (
            <p>
              Create and verify a pre-upgrade backup below. Keep it with the
              earlier installer. Close ReefVision, check the publisher in
              Windows, then open <code>{report.installer}</code> with its
              cabinets in the same folder.
            </p>
          ) : (
            <p>
              Restore the listed files from the original media, remove unrelated
              cabinets from this folder, and verify again.
            </p>
          )}
        </div>
      )}
      <p>
        For rollback, restore the verified pre-upgrade backup into a new folder.
        Open that restored profile with the matching earlier version.
      </p>
      <a href="#system-backups-heading">Go to Backups and restore</a>
    </section>
  );
}
