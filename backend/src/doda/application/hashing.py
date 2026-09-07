"""Canonical hashing for action payloads — underpins approval binding (9.2)
and the audit hash chain (FR-AUD-004). Must be deterministic regardless of
dict key order, since the same logical payload can arrive with keys in any
order from different callers.
"""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
