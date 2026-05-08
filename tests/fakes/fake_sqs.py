"""In-memory fake SQS adapter for unit tests — no external SDK required.

Implements ``SqsAdapter`` (``@runtime_checkable`` Protocol) with a simple
dict-backed queue.  Supports deduplication IDs, in-flight tracking, attempt
counting, and visibility timeout simulation.

References:
  @docs/04-data-stores.md §3.5 (jobs/{job_id}.json — SQS as trigger)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.domain.tenant import TenantContext
from app.infra._base import InfraError
from app.infra.sqs import ReceivedMessage

__all__ = ["FakeSqs"]


@dataclass
class _FakeMessage:
    """Internal in-memory SQS message representation."""

    message_id: str
    body: dict[str, Any]
    dedup_id: str | None
    attempt: int = 1
    receipt_handle: str = field(default_factory=lambda: str(uuid.uuid4()))
    visibility_deadline: float | None = None


class FakeSqs:
    """In-memory fake implementation of ``SqsAdapter``.

    All queues are created on first use.  Messages popped by
    ``receive_messages`` are moved to the in-flight dict; they must be
    explicitly deleted or they remain in-flight (no automatic re-queue in
    the fake).

    Thread-safety: not guaranteed — use one instance per test coroutine.
    """

    def __init__(self) -> None:
        """Initialise empty queue and in-flight stores."""
        self._queues: dict[str, list[_FakeMessage]] = {}
        self._in_flight: dict[str, _FakeMessage] = {}  # receipt_handle → message

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_queue(self, queue_url: str) -> list[_FakeMessage]:
        """Return (or create) the message list for *queue_url*."""
        if queue_url not in self._queues:
            self._queues[queue_url] = []
        return self._queues[queue_url]

    def _has_dedup(self, queue: list[_FakeMessage], dedup_id: str) -> bool:
        """Return ``True`` if a message with *dedup_id* already exists in *queue*."""
        return any(m.dedup_id == dedup_id for m in queue)

    # ------------------------------------------------------------------
    # SqsAdapter interface
    # ------------------------------------------------------------------

    async def send_message(
        self,
        ctx: TenantContext,  # noqa: ARG002
        queue_url: str,
        body: dict[str, Any],
        *,
        deduplication_id: str | None = None,
    ) -> str:
        """Enqueue *body* and return a generated message ID.

        If *deduplication_id* is provided and a message with the same ID
        already exists in the queue, the call is silently deduplicated
        (no error; original message ID is **not** returned — a new UUID is
        returned for interface compliance).

        Args:
            ctx: Tenant context (unused in the fake; present for interface compat).
            queue_url: Queue identifier.
            body: JSON-serialisable message body.
            deduplication_id: Optional FIFO deduplication ID.

        Returns:
            A new ``message_id`` UUID string.
        """
        queue = self._ensure_queue(queue_url)
        if deduplication_id is not None and self._has_dedup(queue, deduplication_id):
            # Deduplicated — return a new id but do NOT enqueue
            return str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        msg = _FakeMessage(
            message_id=message_id,
            body=body,
            dedup_id=deduplication_id,
        )
        queue.append(msg)
        return message_id

    async def receive_messages(
        self,
        queue_url: str,
        *,
        max_messages: int = 1,
        visibility_timeout_s: int = 300,  # noqa: ARG002
        wait_time_s: int = 20,  # noqa: ARG002
    ) -> list[ReceivedMessage]:
        """Pop up to *max_messages* from the queue and move them in-flight.

        Args:
            queue_url: Queue identifier.
            max_messages: Maximum number of messages to pop.
            visibility_timeout_s: Ignored in the fake.
            wait_time_s: Ignored in the fake (no real long-polling).

        Returns:
            List of ``ReceivedMessage`` (may be empty).

        Raises:
            InfraError: If the queue URL is unknown (no messages yet).
        """
        queue = self._queues.get(queue_url, [])
        taken = queue[:max_messages]
        self._queues[queue_url] = queue[max_messages:]
        results: list[ReceivedMessage] = []
        for msg in taken:
            msg.attempt += 1
            self._in_flight[msg.receipt_handle] = msg
            results.append(
                ReceivedMessage(
                    message_id=msg.message_id,
                    receipt_handle=msg.receipt_handle,
                    body=dict(msg.body),
                    attributes={"ApproximateReceiveCount": str(msg.attempt)},
                    attempt=msg.attempt,
                )
            )
        return results

    async def delete_message(
        self,
        queue_url: str,  # noqa: ARG002
        receipt_handle: str,
    ) -> None:
        """Acknowledge and remove an in-flight message.

        Args:
            queue_url: Queue identifier (unused in the fake).
            receipt_handle: Receipt handle from ``receive_messages``.

        Raises:
            InfraError: If the receipt handle is unknown.
        """
        if receipt_handle not in self._in_flight:
            raise InfraError(
                "RECEIPT_HANDLE_NOT_FOUND",
                f"Unknown receipt_handle: {receipt_handle!r}",
            )
        del self._in_flight[receipt_handle]

    async def change_message_visibility(
        self,
        queue_url: str,  # noqa: ARG002
        receipt_handle: str,
        visibility_timeout_s: int,
    ) -> None:
        """Update the visibility deadline for an in-flight message.

        Args:
            queue_url: Queue identifier (unused in the fake).
            receipt_handle: Receipt handle from ``receive_messages``.
            visibility_timeout_s: New visibility timeout in seconds.

        Raises:
            InfraError: If the receipt handle is unknown.
        """
        if receipt_handle not in self._in_flight:
            raise InfraError(
                "RECEIPT_HANDLE_NOT_FOUND",
                f"Unknown receipt_handle: {receipt_handle!r}",
            )
        self._in_flight[receipt_handle].visibility_deadline = float(visibility_timeout_s)
