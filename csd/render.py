"""Stage 2 render: hand-emitted standalone SVG. No graph/layout libraries.

Emit conventions (tests depend on them): class is always the first
attribute; nodes carry data-id; dataflow paths carry data-var.
"""
from .schema import CsdError

NODE_W, NODE_H = 110, 34
COL_W, ROW_H = 150, 90
MARGIN = 40
FRAME_H = 26
BUS_H = 30
GAP = 26
LEGEND_W = 220

MODULE_PALETTE = [
    ("#b2f2bb", "#2f9e44"),  # green
    ("#99e9f2", "#0c8599"),  # cyan
    ("#a5d8ff", "#1971c2"),  # blue
    ("#d0bfff", "#7048e8"),  # purple
    ("#fcc2d7", "#d6336c"),  # pink
    ("#ffec99", "#f08c00"),
    ("#ffc9c9", "#e03131"),
    ("#bac8ff", "#4263eb"),
]
ENTRY_FILL = ("#ffffff", "#343a40")
VAR_PALETTE = [
    "#2f9e44", "#1971c2", "#f76707", "#0ca678",
    "#9c36b5", "#e8590c", "#d6336c", "#495057",
]
ANON_COLOR = "#868e96"
DEAD_COLOR = "#e03131"
CALL_COLOR = "#adb5bd"
TEXT = "#212529"
FONT = 'font-family="sans-serif"'


def module_colors(graph):
    entry_module = graph.meta["entry_point"].rsplit(".", 1)[0]
    colors, i = {}, 0
    for m in sorted({n.module for n in graph.nodes}):
        if m == entry_module:
            colors[m] = ENTRY_FILL
        else:
            colors[m] = MODULE_PALETTE[i % len(MODULE_PALETTE)]
            i += 1
    return colors


def var_colors(graph):
    """Insertion-ordered {var: color}; discarded entry locals are red."""
    ordered, discarded = [], set()
    for local in graph.meta.get("entry_locals", []):
        ordered.append(local["var"])
        if local["status"] == "discarded":
            discarded.add(local["var"])
    for e in sorted(graph.dataflow_edges, key=lambda e: (e.line, e.var)):
        if e.var and e.var not in ordered:
            ordered.append(e.var)
    colors, i = {}, 0
    for var in ordered:
        if var in discarded:
            colors[var] = DEAD_COLOR
        else:
            colors[var] = VAR_PALETTE[i % len(VAR_PALETTE)]
            i += 1
    return colors


class _Geometry:
    def __init__(self, graph, placement):
        entry = graph.meta["entry_point"]
        others = [n for n in graph.nodes if n.id != entry]
        by_order = {}
        for n in others:
            if n.call_order in by_order:
                raise CsdError("duplicate call_order %d" % n.call_order)
            by_order[n.call_order] = n.id
        self.col = {
            by_order[o]: i for i, o in enumerate(sorted(by_order))
        }
        self.ncols = max(len(others), 1)
        self.placement = placement
        above = [placement[n.id][1] for n in others
                 if placement[n.id][0] == "above"]
        below = [placement[n.id][1] for n in others
                 if placement[n.id][0] == "below"]
        rows_above = (max(above) + 1) if above else 0
        rows_below = (max(below) + 1) if below else 0
        self.plot_w = self.ncols * COL_W
        self.above_start = MARGIN + FRAME_H + GAP
        self.bus_y = self.above_start + rows_above * ROW_H
        self.below_start = self.bus_y + BUS_H + GAP
        self.output_y = self.below_start + rows_below * ROW_H + GAP
        self.width = MARGIN * 2 + self.plot_w + LEGEND_W
        self.height = self.output_y + FRAME_H + MARGIN

    def cx(self, nid):
        return MARGIN + self.col[nid] * COL_W + COL_W // 2

    def cy(self, nid):
        side, rank = self.placement[nid]
        start = self.above_start if side == "above" else self.below_start
        return start + rank * ROW_H + ROW_H // 2

    def top(self, nid):
        return self.cy(nid) - NODE_H // 2

    def bottom(self, nid):
        return self.cy(nid) + NODE_H // 2


class _Markers:
    def __init__(self):
        self.ids = {}

    def get(self, color):
        if color not in self.ids:
            self.ids[color] = "m%d" % len(self.ids)
        return self.ids[color]

    def defs(self):
        out = ["<defs>"]
        for color, mid in self.ids.items():
            out.append(
                '<marker id="%s" viewBox="0 0 10 10" refX="9" refY="5" '
                'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                '<path d="M 0 0 L 10 5 L 0 10 z" fill="%s"/></marker>'
                % (mid, color)
            )
        out.append("</defs>")
        return "".join(out)


def _elbow(x1, y1, x2, y2, mid_offset=0):
    if x1 == x2:
        return "M %d %d L %d %d" % (x1, y1, x2, y2)
    mid = (y1 + y2) // 2 + mid_offset
    return "M %d %d V %d H %d V %d" % (x1, y1, mid, x2, y2)


def _path(cls, d, color, markers, var=None, width=2):
    data = ' data-var="%s"' % var if var is not None else ""
    return (
        '<path class="%s"%s d="%s" fill="none" stroke="%s" '
        'stroke-width="%s" marker-end="url(#%s)"/>'
        % (cls, data, d, color, width, markers.get(color))
    )


def _tick(x, y, color):
    return (
        '<line class="tick" x1="%d" y1="%d" x2="%d" y2="%d" '
        'stroke="%s" stroke-width="2.5"/>' % (x - 7, y, x + 7, y, color)
    )


def _label(x, y, text, size=10, anchor="middle", color=TEXT):
    return (
        '<text x="%d" y="%d" %s font-size="%d" text-anchor="%s" '
        'fill="%s">%s</text>' % (x, y, FONT, size, anchor, color, text)
    )


def _trunc(name):
    return name if len(name) <= 16 else name[:15] + "…"


def _io_badge(x, y):
    return (
        '<g class="io-badge"><rect x="%d" y="%d" width="22" height="12" '
        'rx="3" fill="#343a40"/>%s</g>'
        % (x, y, _label(x + 11, y + 9, "IO", size=7, color="#ffffff"))
    )


def render_svg(graph, placement):
    geo = _Geometry(graph, placement)
    entry = graph.meta["entry_point"]
    nodes = {n.id: n for n in graph.nodes}
    mcolors = module_colors(graph)
    vcolors = var_colors(graph)
    markers = _Markers()
    frames, edges, shapes, legends = [], [], [], []

    bar_x, bar_w = MARGIN - 10, geo.plot_w + 20
    for y, name in ((MARGIN, "INPUT"), (geo.output_y, "OUTPUT")):
        frames.append(
            '<rect class="frame" x="%d" y="%d" width="%d" height="%d" '
            'fill="#ffffff" stroke="#868e96"/>' % (bar_x, y, bar_w, FRAME_H)
        )
        frames.append(_label(bar_x + bar_w // 2, y + 17, name, size=12))
    frames.append(
        '<rect class="bus" x="%d" y="%d" width="%d" height="%d" '
        'fill="%s" stroke="%s" stroke-width="1.5"/>'
        % (bar_x, geo.bus_y, bar_w, BUS_H, ENTRY_FILL[0], ENTRY_FILL[1])
    )
    frames.append(
        _label(bar_x + 8, geo.bus_y + 19,
               nodes[entry].qualname + "()", size=11, anchor="start")
    )
    if nodes[entry].has_io:
        frames.append(_io_badge(bar_x + bar_w - 30, geo.bus_y - 6))

    # a colored value edge (or a red dead stub) already shows the call
    # relationship for its pair; grey call arrows are drawn only where no
    # value ties caller and callee together
    plumbed = {
        (l["producer"], l["var"]) for l in graph.meta.get("entry_locals", [])
    }
    entry_linked = {n.id for n in graph.nodes if n.is_dead}
    pair_linked = set()
    for e in graph.dataflow_edges:
        if e.consumer == entry:
            entry_linked.add(e.producer)
            continue
        if (e.producer, e.var) in plumbed:
            entry_linked.add(e.producer)
            entry_linked.add(e.consumer)
        pair_linked.add((e.consumer, e.producer))

    call_chan = 0
    for e in graph.call_edges:
        if e.caller == entry:
            if e.callee in entry_linked:
                continue
            x = geo.cx(e.callee)
            if placement[e.callee][0] == "above":
                d = "M %d %d L %d %d" % (x, geo.bus_y, x, geo.bottom(e.callee))
            else:
                d = "M %d %d L %d %d" % (
                    x, geo.bus_y + BUS_H, x, geo.top(e.callee)
                )
        else:
            if (e.caller, e.callee) in pair_linked:
                continue
            offset = ((call_chan % 5) - 2) * 8
            call_chan += 1
            x1, x2 = geo.cx(e.caller), geo.cx(e.callee)
            if geo.cy(e.callee) >= geo.cy(e.caller):
                d = _elbow(
                    x1, geo.bottom(e.caller), x2, geo.top(e.callee), offset
                )
            else:
                d = _elbow(
                    x1, geo.top(e.caller), x2, geo.bottom(e.callee), offset
                )
        edges.append(_path("call-edge", d, CALL_COLOR, markers, width=1.2))

    # values main plumbs between callees visually return to the bus and
    # re-emerge toward their consumer, instead of drawing a direct edge
    # that reads like a call between the two functions
    seen_segments = set()

    # outgoing values (landing on the bus) ride lanes on the right side of
    # a node's column; incoming values (re-emerging) ride the left side —
    # so opposing arrows at one node never share an x
    lane_counts = {}
    lane_x = {}

    def _lane(node_id, var, direction):
        key = (node_id, var, direction)
        if key not in lane_x:
            n = lane_counts.get((node_id, direction), 0)
            lane_counts[(node_id, direction)] = n + 1
            sign = 1 if direction == "out" else -1
            lane_x[key] = geo.cx(node_id) + sign * (10 + 8 * n)
        return lane_x[key]

    def flow_path(d, seg_color, var):
        key = (d, seg_color)
        if key in seen_segments:
            return
        seen_segments.add(key)
        edges.append(_path("flow-edge", d, seg_color, markers, var))

    flow_chan = 0
    for e in graph.dataflow_edges:
        color = vcolors.get(e.var, ANON_COLOR) if e.var else ANON_COLOR
        if e.consumer == entry:
            x = _lane(e.producer, e.var, "out")
            if placement[e.producer][0] == "below":
                d = "M %d %d L %d %d" % (
                    x, geo.top(e.producer), x, geo.bus_y + BUS_H
                )
                edges.append(_path("flow-edge", d, color, markers, e.var))
                edges.append(_tick(x, geo.bus_y + BUS_H, color))
            else:
                d = "M %d %d L %d %d" % (
                    x, geo.bottom(e.producer), x, geo.bus_y
                )
                edges.append(_path("flow-edge", d, color, markers, e.var))
                edges.append(_tick(x, geo.bus_y, color))
            continue
        pside, cside = placement[e.producer][0], placement[e.consumer][0]
        if (e.producer, e.var) in plumbed or pside != cside:
            # land on the bus at the producer's column, re-emerge at the
            # consumer's, each in its own lane beside the node center
            x1 = _lane(e.producer, e.var, "out")
            x2 = _lane(e.consumer, e.var, "in")
            if pside == "above":
                d1 = "M %d %d L %d %d" % (
                    x1, geo.bottom(e.producer), x1, geo.bus_y
                )
            else:
                d1 = "M %d %d L %d %d" % (
                    x1, geo.top(e.producer), x1, geo.bus_y + BUS_H
                )
            if cside == "above":
                d2 = "M %d %d L %d %d" % (
                    x2, geo.bus_y, x2, geo.bottom(e.consumer)
                )
            else:
                d2 = "M %d %d L %d %d" % (
                    x2, geo.bus_y + BUS_H, x2, geo.top(e.consumer)
                )
            flow_path(d1, color, e.var)
            flow_path(d2, color, e.var)
        else:
            offset = ((flow_chan % 5) - 2) * 8
            flow_chan += 1
            d = _elbow(
                geo.cx(e.producer), geo.bottom(e.producer),
                geo.cx(e.consumer), geo.top(e.consumer),
                offset,
            )
            edges.append(_path("flow-edge", d, color, markers, e.var))

    for n in sorted(nodes.values(), key=lambda n: n.id):
        if n.id == entry:
            continue
        if n.is_dead:
            x = geo.cx(n.id)
            if placement[n.id][0] == "above":
                d = "M %d %d L %d %d" % (x, geo.bottom(n.id), x, geo.bus_y)
                tick_y = geo.bus_y
            else:
                d = "M %d %d L %d %d" % (x, geo.top(n.id), x, geo.bus_y + BUS_H)
                tick_y = geo.bus_y + BUS_H
            edges.append(_path("stub", d, DEAD_COLOR, markers, width=2.5))
            edges.append(_tick(x, tick_y, DEAD_COLOR))
        fill, border = mcolors[n.module]
        cls = "node dead" if n.is_dead else "node"
        stroke = DEAD_COLOR if n.is_dead else border
        swidth = "2.5" if n.is_dead else "1.5"
        cx, cy = geo.cx(n.id), geo.cy(n.id)
        title = "<title>%s</title>" % n.id
        if n.has_loop:
            shapes.append(
                '<ellipse class="%s" data-id="%s" cx="%d" cy="%d" rx="%d" '
                'ry="%d" fill="%s" stroke="%s" stroke-width="%s">%s</ellipse>'
                % (cls, n.id, cx, cy, NODE_W // 2, NODE_H // 2 + 4,
                   fill, stroke, swidth, title)
            )
        else:
            shapes.append(
                '<rect class="%s" data-id="%s" x="%d" y="%d" width="%d" '
                'height="%d" rx="6" fill="%s" stroke="%s" stroke-width="%s">'
                "%s</rect>"
                % (cls, n.id, cx - NODE_W // 2, cy - NODE_H // 2, NODE_W,
                   NODE_H, fill, stroke, swidth, title)
            )
        shapes.append(_label(cx, cy + 3, _trunc(n.qualname)))
        if n.has_io:
            shapes.append(_io_badge(cx + NODE_W // 2 - 14, geo.top(n.id) - 6))

    lx = geo.width - LEGEND_W + 10
    ly = MARGIN
    for m in sorted(mcolors):
        fill, border = mcolors[m]
        legends.append(
            '<g class="legend-module"><rect x="%d" y="%d" width="14" '
            'height="14" fill="%s" stroke="%s"/>%s</g>'
            % (lx, ly, fill, border,
               _label(lx + 22, ly + 11, m.split(".")[-1] + ".py",
                      anchor="start"))
        )
        ly += 20
    ly += 14
    # decision #8: the legend lists BUS-CROSSING variables only (main's
    # tracked locals); other vars still get colors, just no legend row.
    entry_vars = [l["var"] for l in graph.meta.get("entry_locals", [])]
    for var in entry_vars:
        color = vcolors[var]
        arrow = (
            '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
            'stroke-width="2" marker-start="url(#%s)" marker-end="url(#%s)"/>'
            % (lx + 7, ly + 14, lx + 7, ly, color,
               markers.get(color), markers.get(color))
        )
        legends.append(
            '<g class="legend-var">%s%s</g>'
            % (arrow, _label(lx + 22, ly + 11, var, anchor="start"))
        )
        ly += 20

    body = "".join(frames) + "".join(edges) + "".join(shapes) + "".join(legends)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">'
        '<rect x="0" y="0" width="%d" height="%d" fill="#f8f9fa"/>%s%s</svg>'
        % (geo.width, geo.height, geo.width, geo.height,
           geo.width, geo.height, markers.defs(), body)
    )
