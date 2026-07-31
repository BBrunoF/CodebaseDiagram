"""Stage 2 layout.

CallTreeLayout draws the program as an icicle chart of its call tree, so
the picture reads like a successful run:

  - Y is call degree: the entry point at 0, its callees at 1, and so on.
    Degree is the LONGEST path from the entry along call edges, which is
    what guarantees a caller is always drawn above every function it calls
    even when a helper is reachable at several depths.

  - X is a span, not a point. A function's bar covers every function it
    exclusively owns — the ones every path from the entry reaches through
    it (its dominated set). So a bar's width is how much of the program
    that function is solely responsible for, and a callee sitting inside
    its caller's bar *is* the call: no arrow needed to say it.

    A helper called from two places is owned by neither caller; it belongs
    to their nearest common ancestor and keeps an explicit arrow instead.

Functions never reached from the entry get their own band below, laid out
the same way from their own roots.

Alternative strategies implement LayoutStrategy and are drop-in.
"""
from .schema import CsdError

BANDS = ("reached", "unreached")
_VIRTUAL_ROOT = "\x00root"


class LayoutStrategy:
    def layout(self, graph):
        """Return {node_id: (band, degree, column, span)}; band in BANDS."""
        raise NotImplementedError


class CallTreeLayout(LayoutStrategy):
    def layout(self, graph):
        entry = graph.meta["entry_point"]
        order = {n.id: n.call_order for n in graph.nodes}
        ids = set(order)
        if entry not in ids:
            raise CsdError(
                "render needs a real entry function to root the call tree; "
                "pseudo-entry %r cannot be drawn (define main())" % entry
            )
        callees, callers = self._edges(graph, ids)
        reached = self._reachable(entry, callees)
        rest = ids - reached
        roots = {n for n in rest if not (callers.get(n, set()) & rest)}
        placement = {}
        for band, members, band_roots in (
            ("reached", reached, {entry}),
            ("unreached", rest, roots),
        ):
            if not members:
                continue
            degrees = self._degrees(members, callers, band_roots)
            columns = self._columns(members, callers, band_roots, order)
            for nid in members:
                column, span = columns[nid]
                placement[nid] = (band, degrees[nid], column, span)
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
            deep = 0 if (nid in roots or not parents) else (
                max(visit(parent) for parent in parents) + 1
            )
            visiting.discard(nid)
            degree[nid] = deep
            return deep

        for nid in sorted(members):
            visit(nid)
        return degree

    def _dominators(self, members, callers, roots):
        """Immediate dominator per node: the last function every path from a
        root must pass through to reach it."""
        preds = {}
        for nid in members:
            parents = {
                c for c in callers.get(nid, ())
                if c in members and c != nid
            }
            if nid in roots:
                parents.add(_VIRTUAL_ROOT)
            preds[nid] = parents
        universe = set(members) | {_VIRTUAL_ROOT}
        dom = {nid: set(universe) for nid in members}
        dom[_VIRTUAL_ROOT] = {_VIRTUAL_ROOT}
        changed = True
        while changed:
            changed = False
            for nid in sorted(members):
                shared = None
                for parent in preds[nid]:
                    shared = (
                        set(dom[parent]) if shared is None
                        else shared & dom[parent]
                    )
                fresh = ({nid} if shared is None else shared | {nid})
                if fresh != dom[nid]:
                    dom[nid] = fresh
                    changed = True
        idom = {}
        for nid in members:
            candidates = dom[nid] - {nid}
            if candidates:
                idom[nid] = max(
                    candidates, key=lambda d: (len(dom[d]), d)
                )
        return idom

    def _columns(self, members, callers, roots, order):
        """Lay the dominator tree out left to right in call order; a node's
        span is the width of everything it owns."""
        idom = self._dominators(members, callers, roots)
        owned = {}
        for nid, parent in idom.items():
            if parent != _VIRTUAL_ROOT:
                owned.setdefault(parent, []).append(nid)
        columns = {}

        def assign(nid, start):
            children = sorted(
                owned.get(nid, []), key=lambda k: (order[k], k)
            )
            if not children:
                columns[nid] = (start, 1)
                return start + 1
            cursor = start
            for child in children:
                cursor = assign(child, cursor)
            columns[nid] = (start, cursor - start)
            return cursor

        cursor = 0
        for root in sorted(roots, key=lambda k: (order[k], k)):
            cursor = assign(root, cursor)
        for nid in members:
            if nid not in columns:  # defensive: never reached from a root
                columns[nid] = (cursor, 1)
                cursor += 1
        return columns
