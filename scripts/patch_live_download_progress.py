from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


client = Path("apps/web/src/api/client.ts")
replace_once(
    client,
    '''export async function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}`, { signal });
}
''',
    '''export async function getJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobRecord> {
  // Job state changes continuously while a download is active. A unique
  // query value plus fetch cache bypass prevents desktop webviews from
  // reusing the first queued/zero-byte response.
  const pollToken = Date.now();
  return request<JobRecord>(`/jobs/${jobId}?poll=${pollToken}`, {
    signal,
    cache: "no-store",
  });
}
''',
)

manager = Path("apps/web/src/features/models/ModelManager.tsx")
text = manager.read_text(encoding="utf-8")
pattern = re.compile(
    r'''  useEffect\(\(\) => \{\n    if \(!activeJobSignature\) return;\n.*?\n  \}, \[activeJobSignature, project\.id, queryClient\]\);''',
    re.DOTALL,
)
replacement = '''  useEffect(() => {
    if (!activeJobSignature) return;
    let stopped = false;
    let inFlight = false;
    const refresh = async () => {
      // Never stack polling requests. Overlapping responses can arrive out
      // of order and make a live progress bar appear frozen or move backward.
      if (stopped || inFlight) return;
      inFlight = true;
      try {
        const updates = await Promise.all(
          activeJobEntries.map(
            async ([catalogId, jobId]) =>
              [catalogId, await getJob(jobId)] as const,
          ),
        );
        if (stopped) return;
        setInstallJobs((current) => {
          const next = { ...current };
          for (const [catalogId, job] of updates) {
            const previous = next[catalogId];
            const terminal = ![
              "queued",
              "running",
              "cancel_requested",
            ].includes(job.status);
            if (
              terminal ||
              !previous ||
              previous.id !== job.id ||
              job.progress_current >= previous.progress_current
            ) {
              next[catalogId] = job;
            }
          }
          return next;
        });
        if (
          updates.some(
            ([, job]) =>
              !["queued", "running", "cancel_requested"].includes(job.status),
          )
        ) {
          void queryClient.invalidateQueries({
            queryKey: ["model_catalog", project.id],
          });
          void queryClient.invalidateQueries({
            queryKey: ["model_hub_bootstrap", project.id],
          });
        }
      } catch (error) {
        if (!stopped) {
          console.error("Failed to refresh model-install progress", error);
        }
      } finally {
        inFlight = false;
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 500);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [activeJobSignature, project.id, queryClient]);'''
updated, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"Expected one polling effect in {manager}, found {count}")
manager.write_text(updated, encoding="utf-8")

frontend_test = Path("apps/web/src/features/models/ModelManager.test.tsx")
replace_once(
    frontend_test,
    '''    let jobStatus: JobRecord["status"] = "running";
    const job: JobRecord = {''',
    '''    let jobStatus: JobRecord["status"] = "running";
    let jobPollUrl = "";
    let jobPollCache: RequestCache | undefined;
    const job: JobRecord = {''',
)
replace_once(
    frontend_test,
    '''      if (
        url.endsWith("/jobs/job-1") &&
        (!init?.method || init.method === "GET")
      ) {
        return jsonResponse({''',
    '''      if (
        url.includes("/jobs/job-1?poll=") &&
        (!init?.method || init.method === "GET")
      ) {
        jobPollUrl = url;
        jobPollCache = init?.cache;
        return jsonResponse({''',
)
replace_once(
    frontend_test,
    '''    await waitFor(() => expect(screen.getByText(/50%/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));''',
    '''    await waitFor(() => expect(screen.getByText(/50%/)).toBeInTheDocument());
    expect(jobPollUrl).toContain("/jobs/job-1?poll=");
    expect(jobPollCache).toBe("no-store");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));''',
)

backend_test = Path("apps/api/reefvision/tests/test_model_install.py")
backend_text = backend_test.read_text(encoding="utf-8")
test_block = '''\n\ndef test_job_status_response_disables_http_caching(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _mini_entry(b"live-progress")
    _patch_entry(monkeypatch, entry)
    project = create_project(client, "Live install progress")
    endpoint = f"/api/v1/projects/{project['id']}/model-installs/ultralytics%2Fyolo11%2Fdetect%2Fn"
    created = client.post(endpoint, json={"confirmed": True})
    assert created.status_code == 200, created.text

    response = client.get(f"/api/v1/jobs/{created.json()['id']}?poll=1")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
'''
if "def test_job_status_response_disables_http_caching" in backend_text:
    raise RuntimeError("Backend cache regression test already exists")
backend_test.write_text(backend_text.rstrip() + test_block + "\n", encoding="utf-8")
