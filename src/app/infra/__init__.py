"""Infrastructure adapters — all external SDK integrations live here.

Public surface exported from this package:

- ``InfraError``, ``TenantMismatchError`` — base exception classes
- ``EmbeddingsAdapter`` — Bedrock Titan v2 embedding protocol
- ``Neo4jAdapter``, ``Transaction`` — Neo4j async driver protocol
- ``PineconeAdapter``, ``QueryMatch``, ``VectorRecord`` — Pinecone protocol
- ``RedisAdapter``, ``RedisPipeline`` — ElastiCache protocol
- ``ReceivedMessage``, ``SqsAdapter`` — SQS producer/consumer protocol
- ``S3Adapter`` — S3 object storage protocol

All items are ``@runtime_checkable`` Protocol classes (or frozen dataclasses)
so that ``isinstance`` checks work in unit tests with fake implementations.

References:
  @docs/12-coding-conventions.md §3.2 (dependency direction: infra → domain)
  @docs/04-data-stores.md (store schemas and access patterns)
  @docs/05-llm-bedrock.md §5 (Titan embeddings)
"""

from __future__ import annotations

from app.infra._base import InfraError, TenantMismatchError
from app.infra.embeddings import EmbeddingsAdapter
from app.infra.neo4j import Neo4jAdapter, Transaction
from app.infra.pinecone import PineconeAdapter, QueryMatch, VectorRecord
from app.infra.redis import RedisAdapter, RedisPipeline
from app.infra.s3 import S3Adapter
from app.infra.sqs import ReceivedMessage, SqsAdapter

__all__ = [
    "EmbeddingsAdapter",
    "InfraError",
    "Neo4jAdapter",
    "PineconeAdapter",
    "QueryMatch",
    "ReceivedMessage",
    "RedisAdapter",
    "RedisPipeline",
    "S3Adapter",
    "SqsAdapter",
    "TenantMismatchError",
    "Transaction",
    "VectorRecord",
]
