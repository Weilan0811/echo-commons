"""Repository-backed projections supplied to Agent invocations."""

from echo_server.services.context.snapshot_builder import ContextSnapshotBuilder
from echo_server.services.context.source import (
    ContextSnapshotSource,
    EmptyContextSource,
    RepositoryContextSource,
)

__all__ = [
    "ContextSnapshotBuilder",
    "ContextSnapshotSource",
    "EmptyContextSource",
    "RepositoryContextSource",
]
