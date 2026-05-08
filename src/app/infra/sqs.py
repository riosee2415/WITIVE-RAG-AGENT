"""SQS adapter protocol — message queue producer/consumer operations.

``send_message`` accepts a ``TenantContext`` because the caller (pipeline or
api layer) must tag the message with tenant information.  ``receive_messages``,
``delete_message``, and ``change_message_visibility`` operate at the worker
entry-point level and therefore do not require a ``TenantContext``.

References:
  @docs/04-data-stores.md §3.5 (jobs/{job_id}.json — SQS as trigger)
  @docs/08-resilience.md §4 (retry: SDK default for SQS)
  @docs/12-coding-conventions.md §3.2 (dependency direction)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.domain.tenant import TenantContext

__all__ = ["ReceivedMessage", "SqsAdapter"]


@dataclass(frozen=True)
class ReceivedMessage:
    """Immutable representation of a message received from SQS.

    Workers should use ``receipt_handle`` to acknowledge (delete) the
    message after successful processing.  ``attempt`` is 1-based so that
    callers can detect first-attempt vs. retry without parsing attributes.

    Attributes:
        message_id: SQS-assigned message identifier.
        receipt_handle: Opaque token required for acknowledgement and
            visibility-timeout extension calls.
        body: Deserialized message body (JSON object).
        attributes: SQS system attributes (e.g. ``ApproximateReceiveCount``).
        attempt: 1-based receive-count derived from
            ``attributes["ApproximateReceiveCount"]``.

    References: @docs/03-document-pipeline.md §4 (worker processing loop)
    """

    message_id: str
    receipt_handle: str
    body: dict[str, Any]
    attributes: dict[str, str]
    attempt: int


@runtime_checkable
class SqsAdapter(Protocol):
    """Async protocol for SQS message queue operations.

    Producer methods (``send_message``) carry a ``TenantContext`` to allow
    implementations to embed tenant metadata in the message or enforce
    routing rules.  Consumer methods (``receive_messages``, ``delete_message``,
    ``change_message_visibility``) operate at the worker level and do not
    carry a ``TenantContext`` — the worker reads the tenant from the message
    body after receipt.

    Implementations must map all SDK errors to ``InfraError`` subclasses
    and must not use synchronous ``boto3`` calls.

    Retry policy: SDK default (see @docs/08-resilience.md §4).
    """

    async def send_message(
        self,
        ctx: TenantContext,
        queue_url: str,
        body: dict[str, Any],
        *,
        deduplication_id: str | None = None,
    ) -> str:
        """Publish a single message to the SQS queue.

        Args:
            ctx: Tenant context; used to tag or validate the message.
            queue_url: Full SQS queue URL.
            body: Arbitrary JSON-serializable dict to send as the message body.
            deduplication_id: Optional FIFO deduplication ID.  If the queue is
                a standard queue this parameter is silently ignored by SQS.

        Returns:
            SQS-assigned ``MessageId`` of the sent message.

        Raises:
            InfraError: For any SQS/network failure.
        """
        ...

    async def receive_messages(
        self,
        queue_url: str,
        *,
        max_messages: int = 1,
        visibility_timeout_s: int = 300,
        wait_time_s: int = 20,
    ) -> Sequence[ReceivedMessage]:
        """Poll the SQS queue and return up to *max_messages* messages.

        This is the worker entry-point; no ``TenantContext`` is available
        here — the tenant is identified from the message body after receipt.

        Args:
            queue_url: Full SQS queue URL.
            max_messages: Maximum number of messages to retrieve (1-10).
            visibility_timeout_s: Seconds the messages remain invisible to
                other consumers after receipt (default 300 = SQS visibility
                per @docs/08-resilience.md §5.2).
            wait_time_s: Long-polling wait time in seconds (default 20 = max
                SQS long-poll window, reduces empty-receive API cost).

        Returns:
            Sequence of ``ReceivedMessage`` instances (may be empty if the
            queue was empty during the polling window).

        Raises:
            InfraError: For any SQS/network failure.
        """
        ...

    async def delete_message(
        self,
        queue_url: str,
        receipt_handle: str,
    ) -> None:
        """Acknowledge and delete a processed message from the queue.

        Args:
            queue_url: Full SQS queue URL.
            receipt_handle: The ``receipt_handle`` from ``ReceivedMessage``.

        Raises:
            InfraError: For any SQS/network failure.
        """
        ...

    async def change_message_visibility(
        self,
        queue_url: str,
        receipt_handle: str,
        visibility_timeout_s: int,
    ) -> None:
        """Extend (or reduce) the visibility timeout for an in-flight message.

        Used by long-running workers to prevent the message from becoming
        visible again before processing completes.

        Args:
            queue_url: Full SQS queue URL.
            receipt_handle: The ``receipt_handle`` from ``ReceivedMessage``.
            visibility_timeout_s: New visibility timeout in seconds (0-43200).

        Raises:
            InfraError: For any SQS/network failure.
        """
        ...
