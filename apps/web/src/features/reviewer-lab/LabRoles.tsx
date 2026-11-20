import { useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  displayError,
  labRequest,
  localRoleKey,
  type LabRole,
  type LabSession,
} from "./reviewerLabApi";

export function KeyHandoff({
  name,
  roleKey,
  onDismiss,
}: {
  name: string;
  roleKey: string;
  onDismiss: () => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  return (
    <div className="workspace-guide">
      <p>
        Give this key privately to {name}. It will disappear when dismissed.
      </p>
      <label>
        New local role key
        <input
          readOnly
          type={revealed ? "text" : "password"}
          value={roleKey}
          autoComplete="off"
        />
      </label>
      <div className="button-row">
        <button type="button" onClick={() => setRevealed(!revealed)}>
          {revealed ? "Hide key" : "Reveal key"}
        </button>
        <button
          type="button"
          onClick={() =>
            void navigator.clipboard.writeText(roleKey).then(
              () => setCopyStatus("Key copied."),
              () =>
                setCopyStatus(
                  "Clipboard unavailable. Reveal the key to copy it.",
                ),
            )
          }
        >
          Copy key
        </button>
        <button type="button" onClick={onDismiss}>
          Dismiss key
        </button>
      </div>
      {copyStatus && <p role="status">{copyStatus}</p>}
    </div>
  );
}

export function LabAccess({
  projectId,
  initialized,
  onSession,
  children,
}: {
  projectId: string;
  initialized: boolean;
  onSession: (session: LabSession) => void;
  children?: ReactNode;
}) {
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [issued, setIssued] = useState<LabSession>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (initialized) {
        const actor = await labRequest<LabRole>(projectId, "/session", {
          key: key.trim(),
        });
        onSession({ actor, key: key.trim() });
        setKey("");
      } else {
        // Keep the same new key for a safe retry if a response is lost.
        const newKey = key || localRoleKey();
        setKey(newKey);
        const actor = await labRequest<LabRole>(projectId, "/initialize", {
          newKey,
          body: { name },
        });
        setIssued({ actor, key: newKey });
      }
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Local review access" className="panel-card">
      <h3>Local review access</h3>
      {issued ? (
        <KeyHandoff
          name={issued.actor.name}
          roleKey={issued.key}
          onDismiss={() => {
            onSession(issued);
            setKey("");
            setIssued(undefined);
          }}
        />
      ) : (
        <form onSubmit={(event) => void submit(event)}>
          <fieldset className="toolbar-row" disabled={busy}>
            {initialized ? (
              <label>
                Local role key
                <input
                  type="password"
                  autoComplete="off"
                  required
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                />
              </label>
            ) : (
              <label>
                Local manager name
                <input
                  required
                  maxLength={100}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
            )}
            <button type="submit">
              {initialized ? "Open local session" : "Create local manager"}
            </button>
          </fieldset>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {children}
    </section>
  );
}

export function LabRoles({
  projectId,
  session,
  roles,
  onChanged,
}: {
  projectId: string;
  session: LabSession;
  roles: LabRole[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<"reviewer" | "adjudicator">("reviewer");
  const [handoff, setHandoff] = useState<{ name: string; key: string }>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const pending = useRef<{ operation: string; key: string } | undefined>(
    undefined,
  );

  function keyFor(operation: string): string {
    if (pending.current?.operation !== operation) {
      pending.current = { operation, key: localRoleKey() };
    }
    return pending.current.key;
  }

  async function update(
    operation: () => Promise<{ name: string; key?: string }>,
  ) {
    setBusy(true);
    setError("");
    try {
      const created = await operation();
      pending.current = undefined;
      if (created.key) setHandoff({ name: created.name, key: created.key });
      onChanged();
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function issue(event: FormEvent) {
    event.preventDefault();
    await update(async () => {
      const newKey = keyFor(JSON.stringify([name.trim(), role]));
      const created = await labRequest<LabRole>(projectId, "/roles", {
        key: session.key,
        newKey,
        body: { name, role },
      });
      setName("");
      return { name: created.name, key: newKey };
    });
  }

  function revise(participant: LabRole, active: boolean) {
    void update(async () => {
      const newKey = active ? keyFor(participant.id) : undefined;
      const changed = await labRequest<LabRole>(
        projectId,
        "/roles/" + participant.member_id + "/revisions",
        {
          key: session.key,
          newKey,
          body: { base_revision_id: participant.id, active },
        },
      );
      return { name: changed.name, key: newKey };
    });
  }

  return (
    <section aria-label="Local roles" className="panel-card">
      <h3>Local roles</h3>
      <form onSubmit={(event) => void issue(event)}>
        <fieldset className="toolbar-row" disabled={busy || !!handoff}>
          <label>
            Participant name
            <input
              value={name}
              maxLength={100}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Local role
            <select
              value={role}
              onChange={(event) =>
                setRole(
                  event.target.value === "adjudicator"
                    ? "adjudicator"
                    : "reviewer",
                )
              }
            >
              <option value="reviewer">Reviewer</option>
              <option value="adjudicator">Adjudicator</option>
            </select>
          </label>
          <button type="submit">Issue local role</button>
        </fieldset>
      </form>
      {handoff && (
        <KeyHandoff
          name={handoff.name}
          roleKey={handoff.key}
          onDismiss={() => setHandoff(undefined)}
        />
      )}
      <ul>
        {roles.map((participant) => (
          <li key={participant.member_id}>
            {participant.name} · {participant.role} · revision{" "}
            {participant.revision} · {participant.active ? "active" : "revoked"}
            {participant.role !== "manager" && (
              <div className="button-row">
                <button
                  type="button"
                  disabled={busy || !!handoff}
                  onClick={() => revise(participant, true)}
                  aria-label={"Issue new key for " + participant.name}
                >
                  {participant.active ? "Rotate key" : "Reactivate"}
                </button>
                {participant.active && (
                  <button
                    type="button"
                    disabled={busy || !!handoff}
                    onClick={() => revise(participant, false)}
                    aria-label={"Revoke key for " + participant.name}
                  >
                    Revoke
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
