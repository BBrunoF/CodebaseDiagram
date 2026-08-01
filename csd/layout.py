"""Stage 2 layout.

CallTreeLayout draws the program as an icicle chart of its call tree, so
the picture reads like a successful run:

  - A function is drawn once per call path that reaches it. A helper called
    from three places is three bars, each sitting inside the bar that
    called it — the same function running three times, which is what
    actually happens at runtime. Containment therefore expresses EVERY
    call, and no arrow ever has to travel sideways to find a shared helper.

  - Y is depth along that path: the entry point at 0, what it calls at 1.
    Because each bar has exactly one caller, a callee is always directly
    below the bar that called it — no helper sinks below its owner.

  - X is a span: a bar covers every bar underneath it on this path, so its
    width is how much of the run happens inside that call.

Repetition is the trade. A function reachable by many paths is drawn many
times, and a shared subtree is duplicated whole, so a graph with heavy
fan-in gets wide. That is the honest shape of the run: the alternative is
one bar with arrows converging on it from across the diagram.

Recursion is the one call containment cannot express — a function cannot
be drawn inside itself — so a call back into a function already open on
the path stays an explicit dashed back edge.

Functions never reached from the entry get their own band below, laid out
the same way from their own roots.

Alternative strategies implement LayoutStrategy and are drop-in.
"""
from .schema import CsdError, DrawEdge, Layout, Slot

BANDS = ("reached", "unreached")


class LayoutStrategy:
    def layout(self, graph):
        """Return a Layout: {instance key: Slot} plus the arrows to draw."""
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
        sites, callers = self._edges(graph, ids)
        reached = self._reachable(entry, sites)
        rest = ids - reached
        roots = sorted(
            (n for n in rest if not (callers.get(n, set()) & rest)),
            key=lambda k: (order[k], k),
        )
        out = Layout(slots={}, edges=[])
        counters = {}
        for band, members, band_roots in (
            ("reached", reached, [entry]),
            ("unreached", rest, roots),
        ):
            if not members:
                continue
            cursor = 0
            for root in band_roots:
                key = self._key(root, counters)
                cursor = self._expand(
                    root, key, {root: key}, band, 0, cursor, "",
                    sites, order, members, out, counters,
                )
            # defensive: members in no root's subtree (a closed cycle)
            drawn = {s.node_id for s in out.slots.values() if s.band == band}
            for nid in sorted(members - drawn):
                key = self._key(nid, counters)
                out.slots[key] = Slot(band, 0, cursor, 1, nid, "")
                cursor += 1
        return out

    def _key(self, nid, counters):
        seen = counters.get(nid, 0)
        counters[nid] = seen + 1
        return "%s#%d" % (nid, seen)

    def _edges(self, graph, ids):
        """caller -> {callee: [lines]}, keeping every call site."""
        sites, callers = {}, {}
        for edge in graph.call_edges:
            if edge.caller in ids and edge.callee in ids:
                sites.setdefault(edge.caller, {}).setdefault(
                    edge.callee, []
                ).append(edge.line)
                callers.setdefault(edge.callee, set()).add(edge.caller)
        return sites, callers

    def _reachable(self, entry, sites):
        seen = {entry}
        frontier = [entry]
        while frontier:
            current = frontier.pop()
            for callee in sorted(sites.get(current, {})):
                if callee not in seen:
                    seen.add(callee)
                    frontier.append(callee)
        return seen

    def _expand(self, nid, key, path, band, degree, cursor, parent,
                sites, order, members, out, counters):
        """Lay this call out, then everything it calls, left to right in
        call order. `path` maps the functions open above us to their
        instance keys, so a call back into one is a back edge."""
        start = cursor
        children = sorted(
            (c for c in sites.get(nid, {}) if c in members),
            key=lambda c: (order[c], c),
        )
        for callee in children:
            lines = sorted(sites[nid][callee])
            if callee in path:
                # recursion: it re-enters a bar already open on this path,
                # so it cannot be drawn inside itself
                for line in lines:
                    out.edges.append(
                        DrawEdge(key, path[callee], line, "recursion")
                    )
                continue
            child = self._key(callee, counters)
            for line in lines:
                out.edges.append(DrawEdge(key, child, line, "call"))
            cursor = self._expand(
                callee, child, dict(path, **{callee: child}), band,
                degree + 1, cursor, key,
                sites, order, members, out, counters,
            )
        if cursor == start:  # a leaf, or every call from here was recursive
            cursor = start + 1
        out.slots[key] = Slot(band, degree, start, cursor - start, nid, parent)
        return cursor
