"""Stage 2 layout.

CallTreeLayout places every function at its call degree: the entry point at
degree 0, its callees at degree 1, their callees at degree 2, and so on, so
the diagram reads like a successful run of the program.

Degree is the LONGEST path from the entry along call edges. That is what
guarantees the invariant a call tree needs — every caller strictly above
every one of its callees — when a helper is reachable at several depths.

Functions never reached from the entry get their own band below, laid out
the same way from their own roots.

X is not this module's business: the renderer uses the call order the
analyzer already assigned, which is depth-first, so a subtree reads left to
right.

Alternative strategies implement LayoutStrategy and are drop-in.
"""
from .schema import CsdError

BANDS = ("reached", "unreached")


class LayoutStrategy:
    def layout(self, graph):
        """Return {node_id: (band, degree)}; band in BANDS."""
        raise NotImplementedError


class CallTreeLayout(LayoutStrategy):
    def layout(self, graph):
        entry = graph.meta["entry_point"]
        ids = {n.id for n in graph.nodes}
        if entry not in ids:
            raise CsdError(
                "render needs a real entry function to root the call tree; "
                "pseudo-entry %r cannot be drawn (define main())" % entry
            )
        callees, callers = self._edges(graph, ids)
        reached = self._reachable(entry, callees)
        placement = {}
        for nid, degree in self._degrees(reached, callers, {entry}).items():
            placement[nid] = ("reached", degree)
        rest = ids - reached
        roots = {n for n in rest if not (callers.get(n, set()) & rest)}
        for nid, degree in self._degrees(rest, callers, roots).items():
            placement[nid] = ("unreached", degree)
        return placement

    def _edges(self, graph, ids):
        callees, callers = {}, {}
        for edge in graph.call_edges:
            if edge.caller in ids and edge.callee in ids:
                callees.setdefault(edge.caller, set()).add(edge.callee)
                callers.setdefault(edge.callee, set()).add(edge.caller)
        return callees, callers

    def _reachable(self, entry, callees):
        seen = {entry}
        frontier = [entry]
        while frontier:
            current = frontier.pop()
            for callee in sorted(callees.get(current, ())):
                if callee not in seen:
                    seen.add(callee)
                    frontier.append(callee)
        return seen

    def _degrees(self, members, callers, roots):
        """Longest path from a root, so no callee sits level with a caller."""
        degree = {}
        visiting = set()

        def visit(nid):
            if nid in degree:
                return degree[nid]
            if nid in visiting:
                raise CsdError(
                    "call graph cycle involving %s — not handled in v1" % nid
                )
            visiting.add(nid)
            parents = [
                c for c in callers.get(nid, ())
                if c in members and c != nid
            ]
            if nid in roots or not parents:
                deep = 0
            else:
                deep = max(visit(parent) for parent in parents) + 1
            visiting.discard(nid)
            degree[nid] = deep
            return deep

        for nid in sorted(members):
            visit(nid)
        return degree
