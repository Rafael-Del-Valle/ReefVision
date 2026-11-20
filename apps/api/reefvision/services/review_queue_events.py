"""Append-only review-queue coordination; never changes scientific annotations."""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import String, and_, cast, func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.schemas.review_queue_events import (
    REVIEWER_LABEL_DIRECTION_CONTROLS,
    ReviewQueueEventCreate,
    ReviewQueueEventResponse,
    ReviewQueueEventsPage,
)
from reefvision.services.review_queue_transaction_16 import begin_serialized_review_triage


def assert_review_event_action_integrity(session: Session, item_ids: list[str]) -> None:
    """Fail closed for malformed historical QC actions on any selected item.

    Both standalone coordination and saved-workflow bulk triage must reject
    malformed evidence, including off-page and pre-idempotency-key records.
    This is a read-only guard; it never repairs or verifies observations.
    """
    if not item_ids:
        return
    # SQLite's default TRIM strips only ASCII spaces, while Python's
    # str.strip() (used on incoming review actions) also recognizes Unicode
    # whitespace. Imported or restored NBSP/EM SPACE-only labels, comments,
    # assignees and skip reasons must obey that same evidence contract.
    # Explicitly enumerate exactly the Unicode White_Space code points that
    # Python recognizes; SQLite TRIM accepts these characters as its second
    # argument. Do not normalize/modify any persisted reviewer history.
    whitespace = (
        " \t\n\r\f\v\x1c\x1d\x1e\x1f\x85"
        "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
        "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f"
        "\u205f\u3000"
    )
    # SQLAlchemy's SQLite DateTime decoder expects a real ISO timestamp.
    # Restored arbitrary TEXT can instead raise ValueError while rendering
    # history, turning a corrupt event into a 500 and obscuring audit order.
    # Check *every* event before materialization or idempotent replay.
    # Validate canonical application-written UTC-naive SQLite storage; reject
    # hidden NUL, impossible dates and 24:00 (SQLite accepts it but Python
    # datetime does not). No stored event is rewritten or auto-approved.
    sqlite_timestamp_checks: tuple[Any, ...] = ()
    if session.get_bind().dialect.name == "sqlite":
        stored_timestamp = cast(ReviewQueueItemEvent.created_at, String)
        canonical_shape = (
            "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
            "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]."
            "[0-9][0-9][0-9][0-9][0-9][0-9]"
        )
        sqlite_timestamp_checks = (
            ReviewQueueItemEvent.created_at.is_(None),
            func.instr(stored_timestamp, "\x00") > 0,
            func.length(stored_timestamp) != 26,
            # GLOB returns an integer on SQLite. Avoid unary ~ on a String
            # SQLAlchemy expression: SQLAlchemy 2.0.50 treats it as a deprecated
            # inverse on String, failing strict backend CI before audit checks.
            func.glob(canonical_shape, stored_timestamp) == 0,
            func.strftime("%Y-%m-%d %H:%M:%S", stored_timestamp).is_(None),
            func.date(func.substr(stored_timestamp, 1, 10), "+0 days")
            != func.substr(stored_timestamp, 1, 10),
            func.substr(stored_timestamp, 1, 4) == "0000",
            func.substr(stored_timestamp, 12, 2) == "24",
        )

    invalid_event_id = session.scalar(
        select(ReviewQueueItemEvent.id)
        .where(
            ReviewQueueItemEvent.review_queue_item_id.in_(item_ids),
            or_(
                *sqlite_timestamp_checks,
                # SQLite VARCHAR(36) does not enforce UUID length or syntax,
                # and LENGTH(TEXT) stops at NUL. The API converts UUID input
                # to canonical lower-case 8-4-4-4-12 strings; bulk-generated
                # UUIDv5 action keys use the same encoding. Never accept a
                # restored, imported or corrupted audit idempotency identity.
                # Include off-page history before keyed replay or any triage.
                ReviewQueueItemEvent.client_request_id.is_(None),
                func.instr(ReviewQueueItemEvent.client_request_id, "\x00") > 0,
                func.length(ReviewQueueItemEvent.client_request_id) != 36,
                *(
                    func.substr(ReviewQueueItemEvent.client_request_id, position, 1) != "-"
                    for position in (9, 14, 19, 24)
                ),
                func.replace(ReviewQueueItemEvent.client_request_id, "-", "").op("GLOB")(
                    "*[^0123456789abcdef]*"
                ),
                # The self-reported actor is not authentication, but must
                # remain an intelligible audit label.
                # SQLite VARCHAR/TEXT fields do not enforce the length limits
                # of the manual-review API. Imported or restored events must
                # satisfy those same human-evidence limits before history
                # reads, reviewer writes, or keyed bulk replays.
                # SQLite LENGTH(text) stops at the first NUL byte. Reject
                # restored NUL-containing evidence explicitly, so an
                # overlong or hidden label cannot bypass the Unicode limits.
                func.instr(ReviewQueueItemEvent.actor, "\x00") > 0,
                func.instr(ReviewQueueItemEvent.comment, "\x00") > 0,
                func.instr(ReviewQueueItemEvent.assignee, "\x00") > 0,
                # Invisible bidi embedding/override/isolate markers can make
                # imported reviewer labels appear to identify someone else.
                # Check full history, including events outside the current page.
                *(
                    func.instr(column, marker) > 0
                    for column in (ReviewQueueItemEvent.actor, ReviewQueueItemEvent.assignee)
                    for marker in REVIEWER_LABEL_DIRECTION_CONTROLS
                ),
                func.length(ReviewQueueItemEvent.actor) > 100,
                func.length(ReviewQueueItemEvent.comment) > 2000,
                func.length(ReviewQueueItemEvent.assignee) > 100,
                func.trim(ReviewQueueItemEvent.actor, whitespace) == "",
                ~ReviewQueueItemEvent.event_type.in_(
                    (
                        "comment",
                        "assign",
                        "unassign",
                        "triage_start",
                        "triage_skip",
                        "triage_return",
                        "triage_complete",
                    )
                ),
                and_(
                    ReviewQueueItemEvent.event_type == "assign",
                    or_(
                        ReviewQueueItemEvent.assignee.is_(None),
                        func.trim(ReviewQueueItemEvent.assignee, whitespace) == "",
                        ReviewQueueItemEvent.comment.is_not(None),
                    ),
                ),
                and_(
                    ReviewQueueItemEvent.event_type == "unassign",
                    or_(
                        ReviewQueueItemEvent.assignee.is_not(None),
                        ReviewQueueItemEvent.comment.is_not(None),
                    ),
                ),
                and_(
                    ReviewQueueItemEvent.event_type == "comment",
                    or_(
                        ReviewQueueItemEvent.comment.is_(None),
                        func.trim(ReviewQueueItemEvent.comment, whitespace) == "",
                        ReviewQueueItemEvent.assignee.is_not(None),
                    ),
                ),
                and_(
                    ReviewQueueItemEvent.event_type.in_(
                        ("triage_start", "triage_skip", "triage_return", "triage_complete")
                    ),
                    ReviewQueueItemEvent.assignee.is_not(None),
                ),
                # Only skip may carry a reason, and it requires a real one.
                and_(
                    ReviewQueueItemEvent.event_type == "triage_skip",
                    or_(
                        ReviewQueueItemEvent.comment.is_(None),
                        func.trim(ReviewQueueItemEvent.comment, whitespace) == "",
                    ),
                ),
                and_(
                    ReviewQueueItemEvent.event_type.in_(
                        ("triage_start", "triage_return", "triage_complete")
                    ),
                    ReviewQueueItemEvent.comment.is_not(None),
                ),
            ),
        )
        .limit(1)
    )
    if invalid_event_id is not None:
        raise ConflictError("Review event history has inconsistent action evidence")


def validate_review_item_event_scope(
    session: Session, queue_id: str, item_id: str
) -> ReviewQueueItem:
    """Check item, queue, and full action history before any reviewer transition.

    Shared by event endpoints and the four standalone single-item triage
    endpoints, including queues produced by saved Workflow Builder graphs.
    This does not approve observations or repair compromised audit events.
    """
    queue = session.get(ReviewQueue, queue_id)
    if queue is None:
        raise NotFoundError("Review queue not found")
    item = session.get(ReviewQueueItem, item_id)
    if item is None:
        raise NotFoundError("Review queue item not found")
    if item.review_queue_id != queue_id or item.project_id != queue.project_id:
        raise ConflictError("Review item does not belong to this queue")
    if queue.status != "complete":
        raise ConflictError("Review queue is not ready for coordination")
    # Refuse new coordination writes as well as reads when prior reviewer
    # evidence has been moved across project/queue boundaries. Otherwise a
    # fresh request key could append to a scientifically inconsistent history.
    foreign_event_id = session.scalar(
        select(ReviewQueueItemEvent.id)
        .where(
            ReviewQueueItemEvent.review_queue_item_id == item_id,
            (
                (ReviewQueueItemEvent.review_queue_id != queue_id)
                | (ReviewQueueItemEvent.project_id != item.project_id)
            ),
        )
        .limit(1)
    )
    if foreign_event_id is not None:
        raise ConflictError("Review event provenance does not match its queue")

    # External imports may preserve foreign keys yet corrupt an event's
    # action fields. A malformed off-page event must neither give a false
    # current assignee nor permit additional writes onto compromised evidence.
    assert_review_event_action_integrity(session, [item_id])
    return item


def _existing(session: Session, item_id: str, request_id: str) -> ReviewQueueItemEvent | None:
    return session.scalar(
        select(ReviewQueueItemEvent).where(
            ReviewQueueItemEvent.review_queue_item_id == item_id,
            ReviewQueueItemEvent.client_request_id == request_id,
        )
    )


def _same(
    event: ReviewQueueItemEvent,
    payload: ReviewQueueEventCreate,
    *,
    queue_id: str,
    item: ReviewQueueItem,
) -> bool:
    # A request key cannot validate an event whose persisted scientific scope
    # disagrees with the item. Never trust a matching actor/comment alone.
    return (
        event.review_queue_id == queue_id
        and event.review_queue_item_id == item.id
        and event.project_id == item.project_id
        and event.event_type == payload.event_type
        and event.actor == payload.actor
        and event.comment == payload.comment
        and event.assignee == payload.assignee
    )


def _is_sqlite_event_request_collision(exc: IntegrityError) -> bool:
    """Only the event's own idempotency key permits a concurrent replay.

    Unrelated UNIQUE/PRIMARY KEY, foreign-key and NOT NULL violations must
    propagate after rollback; they are not evidence of an identical request.
    """
    if not isinstance(exc.orig, sqlite3.IntegrityError):
        return False
    return getattr(exc.orig, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE and str(
        exc.orig
    ) == (
        "UNIQUE constraint failed: "
        "review_queue_item_events.review_queue_item_id, "
        "review_queue_item_events.client_request_id"
    )


def create_review_event(
    session: Session, queue_id: str, item_id: str, payload: ReviewQueueEventCreate
) -> ReviewQueueEventResponse:
    # Manual comments and assignment changes must serialize with single-item
    # and bulk triage before checking queue scope, existing event keys or the
    # current history. Otherwise separate local SQLite sessions can each
    # accept a stale snapshot and append incompatible researcher decisions.
    # A held writer turn is a retryable conflict, never implicit approval.
    begin_serialized_review_triage(session)
    item = validate_review_item_event_scope(session, queue_id, item_id)
    request_id = str(payload.client_request_id)
    prior = _existing(session, item.id, request_id)
    if prior is not None:
        if not _same(prior, payload, queue_id=queue_id, item=item):
            raise ConflictError("Request ID already used for a different review event")
        return ReviewQueueEventResponse.model_validate(prior)

    event = ReviewQueueItemEvent(
        review_queue_id=queue_id,
        review_queue_item_id=item.id,
        project_id=item.project_id,
        client_request_id=request_id,
        event_type=payload.event_type,
        actor=payload.actor,
        comment=payload.comment,
        assignee=payload.assignee,
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Only a collision on this event's idempotency key can represent a
        # concurrent identical retry. Other integrity failures are defects.
        if not _is_sqlite_event_request_collision(exc):
            raise
        prior = _existing(session, item_id, request_id)
        if prior is None or not _same(prior, payload, queue_id=queue_id, item=item):
            raise ConflictError("Review event request ID conflict") from None
        return ReviewQueueEventResponse.model_validate(prior)
    session.refresh(event)
    return ReviewQueueEventResponse.model_validate(event)


def list_review_events(
    session: Session,
    queue_id: str,
    item_id: str,
    *,
    page: int,
    page_size: int,
) -> ReviewQueueEventsPage:
    # SQLite's implicit SELECT transactions do not always pin a read snapshot.
    # Start one before the queue provenance check, count, event page and
    # assignment lookup: a concurrent editor must not produce a contradictory
    # audit response containing an old total and a new assignment.
    connection = session.connection()
    if connection.dialect.name == "sqlite" and not getattr(
        connection.connection.driver_connection, "in_transaction", False
    ):
        connection.exec_driver_sql("BEGIN")
    validate_review_item_event_scope(session, queue_id, item_id)
    # Local SQLite rowid follows event append order, including when two entries
    # share a timestamp OR the computer clock moves backwards between actions.
    # Ordering primarily by wall-clock time can incorrectly resurrect an
    # earlier assignment after a later unassignment. Other database engines
    # retain timestamp/UUID ordering until a portable durable sequence exists.
    ordering_columns: tuple[Any, ...] = (
        (literal_column("review_queue_item_events.rowid"),)
        if connection.dialect.name == "sqlite"
        else (ReviewQueueItemEvent.created_at, ReviewQueueItemEvent.id)
    )
    filters = [ReviewQueueItemEvent.review_queue_item_id == item_id]
    total = (
        session.scalar(select(func.count()).select_from(ReviewQueueItemEvent).where(*filters)) or 0
    )
    # SQLite LIMIT/OFFSET parameters are signed 64-bit integers. Very large
    # valid page numbers otherwise raise OverflowError at the DB driver,
    # turning a read-only QC history request into an HTTP 500. An offset
    # outside that range is necessarily beyond any SQLite result set; return
    # an empty page while still reporting the real total and current assignee.
    offset = (page - 1) * page_size
    if offset > (1 << 63) - 1:
        events = []
    else:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent)
                .where(*filters)
                .order_by(*ordering_columns)
                .offset(offset)
                .limit(page_size)
            )
        )
    assignment = session.scalar(
        select(ReviewQueueItemEvent)
        .where(
            *filters,
            ReviewQueueItemEvent.event_type.in_(("assign", "unassign")),
        )
        .order_by(*(column.desc() for column in ordering_columns))
        .limit(1)
    )
    return ReviewQueueEventsPage(
        items=[ReviewQueueEventResponse.model_validate(item) for item in events],
        total=total,
        page=page,
        page_size=page_size,
        current_assignee=(
            assignment.assignee
            if assignment is not None and assignment.event_type == "assign"
            else None
        ),
    )
