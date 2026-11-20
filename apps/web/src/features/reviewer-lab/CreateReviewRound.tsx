import { useEffect, useState, type FormEvent } from "react";
import {
  getImages,
  getReviewQueueItems,
  getReviewQueues,
  type ReviewQueueRecord,
} from "../../api/client";
import {
  displayError,
  labRequest,
  type LabRole,
  type LabRound,
  type LabSession,
  type LabSource,
} from "./reviewerLabApi";

type Option = { source: LabSource; label: string; imageId: string };

export function CreateReviewRound({
  projectId,
  session,
  roles,
  onCreated,
}: {
  projectId: string;
  session: LabSession;
  roles: LabRole[];
  onCreated: (round: LabRound) => void;
}) {
  const [title, setTitle] = useState("");
  const [criterion, setCriterion] = useState("");
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [adjudicator, setAdjudicator] = useState("");
  const [queueId, setQueueId] = useState("");
  const [preferred, setPreferred] = useState("");
  const [queues, setQueues] = useState<ReviewQueueRecord[]>([]);
  const [options, setOptions] = useState<Option[]>([]);
  const [selected, setSelected] = useState<Option[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [busy, setBusy] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [error, setError] = useState("");
  const [operation, setOperation] = useState(() => crypto.randomUUID());
  const reviewers = roles.filter(
    (row) => row.active && row.role === "reviewer",
  );
  const adjudicators = roles.filter(
    (row) => row.active && row.role === "adjudicator",
  );

  useEffect(() => {
    const controller = new AbortController();
    void getReviewQueues(projectId, controller.signal).then(
      setQueues,
      (reason: unknown) => {
        if (!controller.signal.aborted) setSourceError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    setSourceError("");
    setOptions([]);
    setPreferred("");
    const sources: Promise<{ options: Option[]; pages: number }> = queueId
      ? getReviewQueueItems(
          queueId,
          { page, pageSize: 30 },
          controller.signal,
        ).then((list) => ({
          options: list.items.map((item) => ({
            source: { type: "queue_item", id: item.id },
            label:
              "Queue rank " +
              item.rank_position +
              " · " +
              item.image_id.slice(0, 8),
            imageId: item.image_id,
          })),
          pages: list.pages,
        }))
      : getImages(projectId, { page, pageSize: 30 }, controller.signal).then(
          (list) => ({
            options: list.items.map((item) => ({
              source: { type: "image", id: item.id },
              label: item.original_filename,
              imageId: item.id,
            })),
            pages: list.pages,
          }),
        );
    void sources.then(
      (list) => {
        if (!controller.signal.aborted) {
          setOptions(list.options);
          setPages(list.pages);
        }
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setSourceError(displayError(reason));
      },
    );
    return () => controller.abort();
  }, [projectId, queueId, page]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const round = await labRequest<LabRound>(projectId, "/rounds", {
        key: session.key,
        body: {
          operation_id: operation,
          title,
          criterion,
          reviewer_member_ids: [first, second],
          adjudicator_member_id: adjudicator,
          sources: selected.map((item) => item.source),
        },
      });
      setTitle("");
      setCriterion("");
      setSelected([]);
      onCreated(round);
    } catch (reason) {
      setError(displayError(reason));
    } finally {
      setBusy(false);
    }
  }

  const change = () => setOperation(crypto.randomUUID());
  const candidate = options.find((option) => option.source.id === preferred);
  return (
    <section aria-label="Plan independent reviews" className="panel-card">
      <h3>Plan independent reviews</h3>
      <form onSubmit={(event) => void submit(event)} onChange={change}>
        <fieldset disabled={busy}>
          <div className="toolbar-row">
            <label>
              Round title
              <input
                value={title}
                maxLength={100}
                required
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label>
              Review criterion
              <textarea
                value={criterion}
                required
                maxLength={1000}
                onChange={(event) => setCriterion(event.target.value)}
              />
            </label>
          </div>
          <div className="toolbar-row">
            {(
              [
                ["First reviewer", first, setFirst, second],
                ["Second reviewer", second, setSecond, first],
              ] as const
            ).map(([label, value, setValue, other]) => (
              <label key={label}>
                {label}
                <select
                  required
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                >
                  <option value="">Choose reviewer</option>
                  {reviewers.map((person) => (
                    <option
                      key={person.member_id}
                      value={person.member_id}
                      disabled={person.member_id === other}
                    >
                      {person.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label>
              Adjudicator
              <select
                required
                value={adjudicator}
                onChange={(event) => setAdjudicator(event.target.value)}
              >
                <option value="">Choose adjudicator</option>
                {adjudicators.map((person) => (
                  <option key={person.member_id} value={person.member_id}>
                    {person.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="toolbar-row">
            <label>
              Source collection
              <select
                value={queueId}
                onChange={(event) => {
                  setQueueId(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">Project images</option>
                {queues.map((queue) => (
                  <option key={queue.id} value={queue.id}>
                    Review queue {queue.id.slice(0, 8)} · {queue.item_count}{" "}
                    items
                  </option>
                ))}
              </select>
            </label>
            <label>
              Original to assign
              <select
                value={preferred}
                onChange={(event) => setPreferred(event.target.value)}
              >
                <option value="">Choose original</option>
                {options.map((item) => (
                  <option key={item.source.id} value={item.source.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={
                !candidate ||
                selected.length >= 100 ||
                selected.some((item) => item.imageId === candidate.imageId)
              }
              onClick={() => {
                if (candidate) setSelected([...selected, candidate]);
                setPreferred("");
                change();
              }}
            >
              Add original
            </button>
          </div>
          {pages > 1 && (
            <div className="button-row">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous source page
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button
                type="button"
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
              >
                Next source page
              </button>
            </div>
          )}
          {sourceError && <p role="alert">{sourceError}</p>}
          <ul>
            {selected.map((item) => (
              <li key={item.source.id}>
                {item.label}{" "}
                <button
                  type="button"
                  aria-label={"Remove " + item.label}
                  onClick={() => {
                    setSelected(
                      selected.filter((selectedItem) => selectedItem !== item),
                    );
                    change();
                  }}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <button type="submit" disabled={!selected.length}>
            Assign blinded reviews
          </button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
