"""Stage 1f: one-hop deadness. No transitive chains in v1."""


def mark_dead(nodes, consumed_producers, resolved_sites):
    """A node is dead iff it returns a value, that value is never consumed
    anywhere, it has no direct IO, and it is actually called (unreached
    functions are never flagged, per the spec)."""
    called = {s.callee for s in resolved_sites}
    for node in nodes.values():
        node.is_dead = (
            node.returns_value
            and not node.has_io
            and node.id in called
            and node.id not in consumed_producers
        )
