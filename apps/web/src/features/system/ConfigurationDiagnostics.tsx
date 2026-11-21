import { useQuery } from "@tanstack/react-query";

import {
  getModelProviders,
  getRuntimeProviderStatuses,
  request,
  type RuntimeProviderStatus,
} from "../../api/client";
import { getPoseInteroperabilityRuntime } from "../video/poseInteroperabilityApi";

interface MachineCompatibility {
  operating_system: string;
  os_release: string;
  os_version: string;
  architecture: string;
  packaged_backend: boolean;
}

const providerStatusLabels: Record<string, string> = {
  ready: "Dependencies ready",
  dependency_missing: "Missing dependency",
  dependency_incompatible: "Incompatible dependency",
  not_implemented: "Catalog only",
  retired_license_audit: "Retired",
};

function RuntimeDetails({ runtime }: { runtime: RuntimeProviderStatus }) {
  return (
    <div>
      <dt>{runtime.display_name}</dt>
      <dd>
        <div>
          {runtime.available
            ? (runtime.package_version ?? "Runtime detected")
            : "Runtime unavailable"}
          {!runtime.available &&
            runtime.package_name &&
            ` · ${runtime.package_name} not detected`}
          {runtime.available && runtime.supports_cpu && " · CPU capability"}
        </div>
        {runtime.cuda_available === true && (
          <div>
            CUDA detected ·{" "}
            {runtime.cuda_device_name ?? "Device name unavailable"}
          </div>
        )}
        {runtime.cuda_available === false &&
          runtime.runtime_id === "pytorch" && (
            <div>
              CUDA unavailable on this backend. Select CPU or check the NVIDIA
              driver and runtime.
            </div>
          )}
        {runtime.runtime_id !== "pytorch" &&
          runtime.notes.map((note) => <div key={note}>{note}</div>)}
      </dd>
    </div>
  );
}

export function ConfigurationDiagnostics() {
  const machine = useQuery({
    queryKey: ["system", "compatibility", "machine"],
    queryFn: ({ signal }) =>
      request<MachineCompatibility>("/system/compatibility/machine", {
        signal,
      }),
  });
  const runtimes = useQuery({
    queryKey: ["system", "compatibility", "runtimes"],
    queryFn: ({ signal }) => getRuntimeProviderStatuses({ signal }),
  });
  const providers = useQuery({
    queryKey: ["system", "compatibility", "providers"],
    queryFn: ({ signal }) => getModelProviders({ signal }),
  });
  const codec = useQuery({
    queryKey: ["system", "compatibility", "pose-codec"],
    queryFn: ({ signal }) => getPoseInteroperabilityRuntime(signal),
  });

  return (
    <section
      className="system-card"
      aria-labelledby="configuration-diagnostics-heading"
    >
      <h3 id="configuration-diagnostics-heading">
        Diagnostics and compatibility
      </h3>
      <div className="system-grid">
        <div>
          <h4>Backend on this machine</h4>
          {machine.isPending && <p role="status">Checking the backend host…</p>}
          {machine.isError && (
            <p>
              Could not check the backend host. Reopen System status to try
              again.
            </p>
          )}
          {machine.data && (
            <dl className="system-list">
              <div>
                <dt>Operating system</dt>
                <dd>
                  {machine.data.operating_system} {machine.data.os_release}
                  {machine.data.os_version && ` · ${machine.data.os_version}`}
                </dd>
              </div>
              <div>
                <dt>Architecture</dt>
                <dd>{machine.data.architecture}</dd>
              </div>
              <div>
                <dt>Backend build</dt>
                <dd>
                  {machine.data.packaged_backend
                    ? "Packaged executable"
                    : "Source environment"}
                </dd>
              </div>
            </dl>
          )}

          <h4>Execution runtimes</h4>
          {runtimes.isPending && (
            <p role="status">Checking runtime dependencies…</p>
          )}
          {runtimes.isError && (
            <p>
              Could not check execution runtimes. Reopen System status to try
              again.
            </p>
          )}
          {runtimes.data && (
            <dl className="system-list">
              {runtimes.data.map((runtime) => (
                <RuntimeDetails key={runtime.runtime_id} runtime={runtime} />
              ))}
            </dl>
          )}
        </div>

        <div>
          <h4>File and project compatibility</h4>
          <dl className="system-list">
            <div>
              <dt>NWB pose exchange</dt>
              <dd>
                {codec.isPending && (
                  <span role="status">Checking the optional codec…</span>
                )}
                {codec.isError && (
                  <span>
                    Could not check the optional codec. Reopen System status to
                    try again.
                  </span>
                )}
                {codec.data?.available && (
                  <span>
                    Codec available · sleap-io {codec.data.installed_version}
                  </span>
                )}
                {codec.data?.available === false && (
                  <>
                    <div>
                      Codec unavailable · requires sleap-io{" "}
                      {codec.data.required_version}
                    </div>
                    {codec.data.reason && <div>{codec.data.reason}</div>}
                    <div>
                      Use COCO or DeepLabCut CSV in Video &amp; tracking for
                      neutral pose exchange.
                    </div>
                  </>
                )}
              </dd>
            </div>
            <div>
              <dt>Project Exchange</dt>
              <dd>
                Inspect a project exchange ZIP in Interoperability to check the
                format and its contents before importing.
              </dd>
            </div>
            <div>
              <dt>Project database</dt>
              <dd>
                Check the Database card for schema and read/write status. Use
                Backups and restore to verify a managed backup.
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <details>
        <summary>Model provider status</summary>
        <p>Check a specific checkpoint and task in Model Hub.</p>
        {providers.isPending && <p role="status">Checking model providers…</p>}
        {providers.isError && (
          <p>
            Could not check model providers. Reopen System status to try again.
          </p>
        )}
        {providers.data && (
          <dl className="system-list">
            {providers.data.map((provider) => (
              <div key={provider.provider_id}>
                <dt>{provider.display_name}</dt>
                <dd>
                  <div>
                    {providerStatusLabels[provider.availability_status] ??
                      provider.availability_status.replaceAll("_", " ")}
                  </div>
                  {provider.availability_reason && (
                    <div>{provider.availability_reason}</div>
                  )}
                  {provider.supported_tasks.length > 0 && (
                    <div>
                      Declared tasks · {provider.supported_tasks.join(", ")}
                    </div>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </details>

      <details>
        <summary>Previously tested Windows configurations</summary>
        <p>
          <strong>ReefVision 1.8.0 original MSI</strong> ·{" "}
          <code>e3e8ffb63</code>
        </p>
        <dl className="system-list">
          <div>
            <dt>Windows Server 2022 x64 · standard account</dt>
            <dd>
              Fresh registered installation, first use, and project workflows
              without GPU acceleration.
            </dd>
          </div>
          <div>
            <dt>Windows 11 Home x64 · build 10.0.26300</dt>
            <dd>
              Native WebView2 on the extracted package. NVIDIA GeForce RTX 3090
              with driver 617.42 and PyTorch 2.5.1+cu121 ran detector,
              segmentation, and native ReefPose jobs. The detector and
              segmentation jobs used Ultralytics. COCO pose exchange and a
              historical Project Exchange 1.0 archive were also exercised on
              this package.
            </dd>
          </div>
          <div>
            <dt>Project profiles on the hosted Windows installer</dt>
            <dd>
              Upgrade and recovery checks used generated profiles from published
              1.0.3 and the validated 1.3, 1.4, 1.5, 1.6 and 1.7 packages. The
              historical 0038 and 0039 database snapshots were checked
              separately.
            </dd>
          </div>
        </dl>
        <p>
          <a href="https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44853957856">
            Original Windows installer evidence
          </a>
        </p>
      </details>
    </section>
  );
}
