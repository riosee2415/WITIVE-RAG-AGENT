"""Protocol compliance tests — all 7 fakes pass isinstance checks.

Verifies that every fake adapter is a structural subtype of its corresponding
``@runtime_checkable`` Protocol, so that pipeline code can accept them
interchangeably with the real adapters.

References:
  @docs/11-testing.md §3 (fake adapter pattern)
  @docs/12-coding-conventions.md §7.2 (Protocol for infra interfaces)
"""

from __future__ import annotations

from app.infra.embeddings import EmbeddingsAdapter
from app.infra.neo4j import Neo4jAdapter, Transaction
from app.infra.pinecone import PineconeAdapter
from app.infra.redis import RedisAdapter, RedisPipeline
from app.infra.s3 import S3Adapter
from app.infra.sqs import SqsAdapter
from tests.fakes.fake_embeddings import FakeEmbeddings
from tests.fakes.fake_neo4j import FakeNeo4j, _FakeTransaction
from tests.fakes.fake_pinecone import FakePinecone
from tests.fakes.fake_redis import FakeRedis, _FakeRedisPipeline
from tests.fakes.fake_s3 import FakeS3
from tests.fakes.fake_sqs import FakeSqs


class TestProtocolCompliance:
    """All 7 fake adapters must satisfy isinstance() against their Protocols."""

    def test_fake_s3_is_s3adapter(self) -> None:
        assert isinstance(FakeS3(), S3Adapter)

    def test_fake_sqs_is_sqsadapter(self) -> None:
        assert isinstance(FakeSqs(), SqsAdapter)

    def test_fake_pinecone_is_pineconoadapter(self) -> None:
        assert isinstance(FakePinecone(), PineconeAdapter)

    def test_fake_neo4j_is_neo4jadapter(self) -> None:
        assert isinstance(FakeNeo4j(), Neo4jAdapter)

    def test_fake_embeddings_is_embeddingsadapter(self) -> None:
        assert isinstance(FakeEmbeddings(), EmbeddingsAdapter)

    def test_fake_redis_is_redisadapter(self) -> None:
        assert isinstance(FakeRedis(), RedisAdapter)

    def test_fake_redis_pipeline_is_redispipeline(self) -> None:
        from tests.fakes.fake_redis import _FakeClock

        clock = _FakeClock()
        pipe = _FakeRedisPipeline({}, clock)
        assert isinstance(pipe, RedisPipeline)

    def test_fake_transaction_is_transaction_protocol(self) -> None:
        tx = _FakeTransaction({})
        assert isinstance(tx, Transaction)
