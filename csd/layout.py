"""Stage 2 layout. BusLayout implements the approved design:

- the entry function is a full-width bus,
- the output-chain tail (walk main's calls backward from its output sink;
  the unbroken value-handoff chain) hangs below, with its helper subtrees,
- everything else hangs above,
- within each half, rank = longest-path dataflow order (producer above
  consumer); dataflow-isolated nodes sit at the rank nearest the bus.

Alternative strategies implement LayoutStrategy and are drop-in.
"""
from .schema import CsdError

_ENTRY_SINKS = ("external_call", "return")


class LayoutStrategy:
    def layout(self, graph):
        """Return {node_id: (side, rank)}; side in {"bus", "above", "below"}."""
        raise NotImplementedError


class BusLayout(LayoutStrategy):
    def layout(self, graph):
        entry = graph.meta["entry_point"]
        ids = {n.id for n in graph.nodes}
        if entry not in ids:
            raise CsdError(
                "render needs a real entry function for the bus; "
                "pseudo-entry %r cannot be drawn (define main())" % entry
            )
        chain = self._output_chain(graph, entry)
        below = self._call_reachable(graph, chain, exclude={entry})
        above = ids - below - {entry}
        placement = {entry: ("bus", 0)}
        for side_name, members in (("above", above), ("below", below)):
            ranks = self._ranks(graph, members)
            if side_name == "below":
                involved = {
                    e.producer for e in graph.dataflow_edges
                    if e.producer in members and e.consumer in members
                } | {
                    e.consumer for e in graph.dataflow_edges
                    if e.producer in members and e.consumer in members
                }
                for nid in members:
                    if nid not in involved:
                        ranks[nid] = 0
            for nid in members:
                placement[nid] = (side_name, ranks[nid])
        return placement

    def _output_chain(self, graph, entry):
        entry_edges = [
            e for e in graph.dataflow_edges
            if e.consumer == entry and e.consumed_by in _ENTRY_SINKS
        ]
        if not entry_edges:
            return set()
        sink = max(entry_edges, key=lambda e: e.line)
        main_calls = sorted(
            (e for e in graph.call_edges if e.caller == entry),
            key=lambda e: e.line,
        )
        start = None
        for i, edge in enumerate(main_calls):
            if edge.callee == sink.producer and edge.line <= sink.line:
                start = i
        if start is None:
            return {sink.producer}
        chain = {sink.producer}
        for j in range(start - 1, -1, -1):
            callee = main_calls[j].callee
            feeds_chain = any(
                e.producer == callee
                and (
                    e.consumer in chain
                    or (e.consumer == entry and e.consumed_by in _ENTRY_SINKS)
                )
                for e in graph.dataflow_edges
            )
            if not feeds_chain:
                break
            chain.add(callee)
        return chain

    def _call_reachable(self, graph, seeds, exclude):
        out = set(seeds)
        frontier = list(seeds)
        while frontier:
            current = frontier.pop()
            for e in graph.call_edges:
                if e.caller == current and e.callee not in out | exclude:
                    out.add(e.callee)
                    frontier.append(e.callee)
        return out

    def _ranks(self, graph, members):
        preds = {nid: set() for nid in members}
        has_edge = set()
        for e in graph.dataflow_edges:
            if e.producer in members and e.consumer in members:
                preds[e.consumer].add(e.producer)
                has_edge.add(e.producer)
                has_edge.add(e.consumer)
        rank = {}
        visiting = set()

        def visit(nid):
            if nid in rank:
                return rank[nid]
            if nid in visiting:
                raise CsdError(
                    "dataflow cycle involving %s — not handled in v1" % nid
                )
            visiting.add(nid)
            r = 0
            for p in preds[nid]:
                r = max(r, visit(p) + 1)
            visiting.discard(nid)
            rank[nid] = r
            return r

        for nid in sorted(members):
            visit(nid)
        max_rank = max((rank[n] for n in has_edge), default=0)
        for nid in members:
            if nid not in has_edge:
                rank[nid] = max_rank
        return rank
