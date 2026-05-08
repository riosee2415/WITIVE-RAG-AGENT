"""Pinecone metadata filter DSL evaluator — no external SDK required.

Implements the subset of Pinecone filter operators used by this service:
  ``$eq``, ``$ne``, ``$in``, ``$nin``, ``$lt``, ``$lte``, ``$gt``, ``$gte``,
  ``$and``, ``$or``.

Reference: @docs/04-data-stores.md §1.4 (filter DSL usage)

Usage::

    from tests.fakes._filter import eval_filter

    passes = eval_filter(
        filter={"$and": [{"access_level": "COMPANY_WIDE"}, {"archived": False}]},
        metadata={"access_level": "COMPANY_WIDE", "archived": False},
    )
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def eval_filter(
    filter: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> bool:
    """Evaluate a Pinecone-style metadata filter against a metadata mapping.

    Args:
        filter: A Pinecone filter dict.  Top-level keys are either logical
            operators (``$and``, ``$or``) or field names.  Field-level values
            are either a scalar (equality shorthand) or an operator dict
            (``{"$eq": value}``, etc.).
        metadata: The vector metadata to test.

    Returns:
        ``True`` if *metadata* satisfies all conditions in *filter*.
    """
    return _eval_node(filter, metadata)


def _eval_node(node: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    """Recursively evaluate a single filter node."""
    for key, value in node.items():
        if key == "$and":
            if not isinstance(value, list):
                return False
            if not all(_eval_node(clause, metadata) for clause in value):
                return False
        elif key == "$or":
            if not isinstance(value, list):
                return False
            if not any(_eval_node(clause, metadata) for clause in value):
                return False
        else:
            # Field-level comparison
            field_val = metadata.get(key)
            if not _eval_field(value, field_val):
                return False
    return True


def _eval_field(condition: Any, field_val: Any) -> bool:
    """Evaluate a field-level condition.

    Args:
        condition: Either a scalar (equality shorthand) or an operator dict.
        field_val: The current value of the metadata field.

    Returns:
        ``True`` if the condition is satisfied.
    """
    if not isinstance(condition, dict):
        # Scalar shorthand: {"field": value} means equality
        return bool(field_val == condition)

    for op, operand in condition.items():
        if op == "$eq":
            if field_val != operand:
                return False
        elif op == "$ne":
            if field_val == operand:
                return False
        elif op == "$in":
            # field_val must be a scalar in the operand list
            # OR field_val is a list and any element is in operand list
            if isinstance(field_val, list):
                if not any(item in operand for item in field_val):
                    return False
            else:
                if field_val not in operand:
                    return False
        elif op == "$nin":
            if isinstance(field_val, list):
                if any(item in operand for item in field_val):
                    return False
            else:
                if field_val in operand:
                    return False
        elif op == "$lt":
            if field_val is None or field_val >= operand:
                return False
        elif op == "$lte":
            if field_val is None or field_val > operand:
                return False
        elif op == "$gt":
            if field_val is None or field_val <= operand:
                return False
        elif op == "$gte":
            if field_val is None or field_val < operand:
                return False
        else:
            # Unknown operator — fail closed
            return False
    return True
