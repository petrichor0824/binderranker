"""Thin protocol adapters for the BinderRanker Tool API.

Adapters translate transport-specific requests into the framework-independent
Tool API.  They do not own scientific ranking, approval, execution, or result
validation behavior.
"""

from protein_design_agent.adapters.read_only import (
    READ_ONLY_ADAPTER_OPERATIONS,
    ReadOnlyToolAdapter,
)

__all__ = [
    "READ_ONLY_ADAPTER_OPERATIONS",
    "ReadOnlyToolAdapter",
]
