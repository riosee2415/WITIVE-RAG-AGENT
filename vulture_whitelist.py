"""Vulture whitelist — Protocol interface method parameters.

Protocol methods only have ``...`` as their body; all parameters are
intentionally unused in the definition (they document the expected call
signature for implementors).  Vulture cannot distinguish Protocol stubs
from real dead code, so we whitelist them here.

This file is never imported at runtime — it is only consumed by vulture.
"""

# app.infra.embeddings — EmbeddingsAdapter Protocol stubs
texts = None
text = None
model = None

# app.infra.neo4j — Neo4jAdapter / Transaction Protocol stubs
cypher = None
params = None
work = None

# app.infra.pinecone — PineconeAdapter Protocol stubs
vector = None
top_k = None
filter = None
include_metadata = None
vectors = None
vector_ids = None
vector_id = None

# app.infra.redis — RedisAdapter / RedisPipeline Protocol stubs
ttl_s = None

# app.infra.s3 — S3Adapter Protocol stubs
body = None
content_type = None
sse_kms_key_id = None
byte_range = None
if_match = None
prefix = None
max_keys = None
src_key = None
dst_key = None
body_iterator = None

# app.infra.sqs — SqsAdapter Protocol stubs
queue_url = None
deduplication_id = None
max_messages = None
visibility_timeout_s = None
wait_time_s = None
receipt_handle = None
