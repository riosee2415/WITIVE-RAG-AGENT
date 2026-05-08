"""In-memory fake infrastructure adapters for unit tests.

All fakes implement the corresponding ``@runtime_checkable`` Protocol from
``app.infra``.  No external SDK is imported anywhere in this package.

Usage::

    from tests.fakes import FakeS3, FakeSqs, FakePinecone, FakeNeo4j
    from tests.fakes import FakeEmbeddings, FakeRedis

References:
  @docs/11-testing.md §3 (fake adapter pattern)
  @docs/07-multitenancy-and-access.md §2.2 (tenant isolation enforcement)
"""

from __future__ import annotations

from tests.fakes.fake_embeddings import FakeEmbeddings
from tests.fakes.fake_neo4j import FakeNeo4j
from tests.fakes.fake_pinecone import FakePinecone
from tests.fakes.fake_redis import FakeRedis
from tests.fakes.fake_s3 import FakeS3
from tests.fakes.fake_sqs import FakeSqs

__all__ = [
    "FakeEmbeddings",
    "FakeNeo4j",
    "FakePinecone",
    "FakeRedis",
    "FakeS3",
    "FakeSqs",
]
