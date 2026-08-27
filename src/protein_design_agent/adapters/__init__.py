"""Thin protocol adapters for the BinderRanker Tool API.

Adapters translate transport-specific requests into the framework-independent
Tool API.  They do not own scientific ranking, approval, execution, or result
validation behavior.
"""

from protein_design_agent.adapters.read_only import (
    READ_ONLY_ADAPTER_OPERATIONS,
    ReadOnlyToolAdapter,
)
from protein_design_agent.adapters.tunnel_readiness import (
    PrivateTunnelReadinessReport,
    assess_private_tunnel_readiness,
)

__all__ = [
    "READ_ONLY_ADAPTER_OPERATIONS",
    "PrivateTunnelReadinessReport",
    "ReadOnlyToolAdapter",
    "assess_private_tunnel_readiness",
]
