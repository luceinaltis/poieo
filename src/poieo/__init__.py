"""poieo -- a harness that separates logical workflows from physical models.

A *graph* says what work happens and in what order; it names logical roles.
A *binding* says which provider and model serves each role. The runtime walks
the graph, and the daemon keeps flows running on triggers.
"""

from .binding import BindingSpec, load_binding
from .errors import (
    BindingError,
    ExpressionError,
    NodeError,
    PoieoError,
    ProviderError,
    RunAborted,
    SpecError,
)
from .graph import GraphSpec, load_graph
from .providers import ProviderPool
from .runtime import RunResult, execute
from .store import RunStore

__version__ = "0.1.0"

__all__ = [
    "BindingError",
    "BindingSpec",
    "ExpressionError",
    "GraphSpec",
    "NodeError",
    "PoieoError",
    "ProviderError",
    "ProviderPool",
    "RunAborted",
    "RunResult",
    "RunStore",
    "SpecError",
    "execute",
    "load_binding",
    "load_graph",
]
