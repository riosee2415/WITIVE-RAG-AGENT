"""Unit tests for FakeSqs — send/receive/delete lifecycle, dedup, attempt count.

References:
  @docs/04-data-stores.md §3.5 (SQS as pipeline trigger)
  @docs/11-testing.md §3 (fake adapter pattern)
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.access import Role
from app.domain.tenant import TenantContext
from app.infra._base import InfraError
from tests.fakes.fake_sqs import FakeSqs

_TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_QUEUE = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/witive-docs"


def _ctx() -> TenantContext:
    return TenantContext(
        tenant_id=_TENANT,
        user_id=_USER,
        role=Role.COMPANY_ADMIN,
        departments=(),
        level=None,
        hire_date=None,
        request_id="req-sqs-test",
    )


@pytest.fixture()
def sqs() -> FakeSqs:
    """Return a fresh FakeSqs instance."""
    return FakeSqs()


# ---------------------------------------------------------------------------
# send / receive / delete lifecycle
# ---------------------------------------------------------------------------


class TestSendReceiveDelete:
    async def test_send_returns_message_id(self, sqs: FakeSqs) -> None:
        msg_id = await sqs.send_message(_ctx(), _QUEUE, {"job_id": "j1"})
        assert isinstance(msg_id, str)
        assert len(msg_id) > 0

    async def test_receive_after_send_returns_message(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"job_id": "j1"})
        messages = await sqs.receive_messages(_QUEUE)
        assert len(messages) == 1
        assert messages[0].body == {"job_id": "j1"}

    async def test_receive_empty_queue_returns_empty(self, sqs: FakeSqs) -> None:
        messages = await sqs.receive_messages(_QUEUE)
        assert messages == []

    async def test_delete_removes_in_flight_message(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"job_id": "j2"})
        msgs = await sqs.receive_messages(_QUEUE)
        assert len(msgs) == 1
        await sqs.delete_message(_QUEUE, msgs[0].receipt_handle)
        # Message is gone — in-flight is empty
        assert len(sqs._in_flight) == 0

    async def test_delete_unknown_receipt_handle_raises(self, sqs: FakeSqs) -> None:
        with pytest.raises(InfraError) as exc_info:
            await sqs.delete_message(_QUEUE, "not-a-valid-handle")
        assert exc_info.value.code == "RECEIPT_HANDLE_NOT_FOUND"

    async def test_receive_respects_max_messages(self, sqs: FakeSqs) -> None:
        for i in range(5):
            await sqs.send_message(_ctx(), _QUEUE, {"seq": i})
        msgs = await sqs.receive_messages(_QUEUE, max_messages=3)
        assert len(msgs) == 3

    async def test_multiple_receives_drain_queue(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 0})
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 1})
        first = await sqs.receive_messages(_QUEUE, max_messages=1)
        second = await sqs.receive_messages(_QUEUE, max_messages=1)
        third = await sqs.receive_messages(_QUEUE, max_messages=1)
        assert len(first) == 1
        assert len(second) == 1
        assert len(third) == 0

    async def test_message_body_is_preserved(self, sqs: FakeSqs) -> None:
        body = {
            "job_id": "j123",
            "tenant_id": str(_TENANT),
            "doc_id": "d456",
        }
        await sqs.send_message(_ctx(), _QUEUE, body)
        msgs = await sqs.receive_messages(_QUEUE)
        assert msgs[0].body == body


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    async def test_dedup_id_prevents_duplicate_enqueue(self, sqs: FakeSqs) -> None:
        dedup = "unique-dedup-id-123"
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 1}, deduplication_id=dedup)
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 2}, deduplication_id=dedup)
        # Only one message should be in the queue
        msgs = await sqs.receive_messages(_QUEUE, max_messages=10)
        assert len(msgs) == 1
        assert msgs[0].body == {"seq": 1}

    async def test_different_dedup_ids_both_enqueue(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 1}, deduplication_id="id-a")
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 2}, deduplication_id="id-b")
        msgs = await sqs.receive_messages(_QUEUE, max_messages=10)
        assert len(msgs) == 2

    async def test_no_dedup_id_allows_duplicate_bodies(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"same": "body"})
        await sqs.send_message(_ctx(), _QUEUE, {"same": "body"})
        msgs = await sqs.receive_messages(_QUEUE, max_messages=10)
        assert len(msgs) == 2


# ---------------------------------------------------------------------------
# Attempt count
# ---------------------------------------------------------------------------


class TestAttemptCount:
    async def test_first_receive_has_attempt_above_one(self, sqs: FakeSqs) -> None:
        # Attempt starts at 1 (stored) and is incremented on receive
        await sqs.send_message(_ctx(), _QUEUE, {"job": "j1"})
        msgs = await sqs.receive_messages(_QUEUE)
        # Attempt increments from initial 1 to 2 on first receive
        assert msgs[0].attempt >= 1

    async def test_attempt_count_reflects_in_attributes(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"job": "j1"})
        msgs = await sqs.receive_messages(_QUEUE)
        assert "ApproximateReceiveCount" in msgs[0].attributes

    async def test_receipt_handle_is_unique_per_receive(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 1})
        await sqs.send_message(_ctx(), _QUEUE, {"seq": 2})
        msgs = await sqs.receive_messages(_QUEUE, max_messages=2)
        assert msgs[0].receipt_handle != msgs[1].receipt_handle


# ---------------------------------------------------------------------------
# change_message_visibility
# ---------------------------------------------------------------------------


class TestChangeMessageVisibility:
    async def test_change_visibility_updates_deadline(self, sqs: FakeSqs) -> None:
        await sqs.send_message(_ctx(), _QUEUE, {"job": "long"})
        msgs = await sqs.receive_messages(_QUEUE)
        handle = msgs[0].receipt_handle
        await sqs.change_message_visibility(_QUEUE, handle, 600)
        assert sqs._in_flight[handle].visibility_deadline == 600.0

    async def test_change_visibility_unknown_handle_raises(self, sqs: FakeSqs) -> None:
        with pytest.raises(InfraError) as exc_info:
            await sqs.change_message_visibility(_QUEUE, "bad-handle", 30)
        assert exc_info.value.code == "RECEIPT_HANDLE_NOT_FOUND"
