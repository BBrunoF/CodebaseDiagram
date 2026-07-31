"""Stage 2 render: hand-emitted standalone SVG. No graph/layout libraries.

The picture is a call tree read as a successful run:

  - Y is call degree, so a caller is always above every function it calls.
  - X is call order (depth-first), so a subtree reads left to right.
  - Grey arrows going down are calls. That is the skeleton, always drawn.
  - Colored arrows coming back up are the returned values, one per call.
  - A dead value's return never reaches its caller: it stops in a red stub.

Emit conventions (tests depend on them): class is always the first
attribute; nodes carry data-id; return arrows carry data-var.
"""
from .schema import CsdError

NODE_W, NODE_H = 118, 34
COL_W, ROW_H = 150, 96
MARGIN = 40
BAND_GAP = 84
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
MUTED = "#868e96"
FONT = 'font-family="sans-serif"'


def module_colors(graph):
    entry_module = graph.meta["entry_point"].rsplit(".", 1)[0]
    colors, i = {}, 0
    for module in sorted({n.module for n in graph.nodes}):
        if module == entry_module:
            colors[module] = ENTRY_FILL
        else:
            colors[module] = MODULE_PALETTE[i % len(MODULE_PALETTE)]
            i += 1
    return colors


def var_colors(graph):
    """Insertion-ordered {var: color}; discarded entry locals are red."""
    ordered, discarded = [], set()
    for local in graph.meta.get("entry_locals", []):
        ordered.append(local["var"])
        if local["status"] == "discarded":
            discarded.add(local["var"])
    for edge in sorted(graph.dataflow_edges, key=lambda e: (e.line, e.var)):
        if edge.var and edge.var not in ordered:
            ordered.append(edge.var)
    colors, i = {}, 0
    for var in ordered:
        if var in discarded:
            colors[var] = DEAD_COLOR
        else:
            colors[var] = VAR_PALETTE[i % len(VAR_PALETTE)]
            i += 1
    return colors


def producer_vars(graph):
    """{producer id: the name its returned value is known by}."""
    named = {}
    for local in graph.meta.get("entry_locals", []):
        named.setdefault(local["producer"], local["var"])
    for edge in sorted(graph.dataflow_edges, key=lambda e: (e.line, e.var)):
        if edge.var:
            named.setdefault(edge.producer, edge.var)
    return named


class _Geometry:
    """Columns are packed per band so neither band drifts off to one side."""

    def __init__(self, graph, placement):
        nodes = {n.id: n for n in graph.nodes}
        members = {}
        for nid, (band, _) in placement.items():
            if nid not in nodes:
                raise CsdError("placement names unknown node %s" % nid)
            members.setdefault(band, []).append(nid)
        self.placement = placement
        self.col = {}
        self.band_top = {}
        widest = 0
        top = MARGIN
        for band in ("reached", "unreached"):
            group = members.get(band)
            if not group:
                continue
            for column, nid in enumerate(
                sorted(group, key=lambda i: nodes[i].call_order)
            ):
                self.col[nid] = column
            widest = max(widest, len(group))
            self.band_top[band] = top
            rows = max(placement[nid][1] for nid in group) + 1
            top += rows * ROW_H + BAND_GAP
        self.plot_w = widest * COL_W
        self.width = MARGIN * 2 + self.plot_w + LEGEND_W
        self.height = top - BAND_GAP + MARGIN

    def cx(self, nid):
        return MARGIN + self.col[nid] * COL_W + COL_W // 2

    def cy(self, nid):
        band, degree = self.placement[nid]
        return self.band_top[band] + degree * ROW_H + 30

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


def _path(cls, d, color, markers, var=None, width=1.6):
    data = ' data-var="%s"' % var if var is not None else ""
    return (
        '<path class="%s"%s d="%s" fill="none" stroke="%s" '
        'stroke-width="%s" marker-end="url(#%s)"/>'
        % (cls, data, d, color, width, markers.get(color))
    )


def _label(x, y, text, size=10, anchor="middle", color=TEXT):
    return (
        '<text x="%d" y="%d" %s font-size="%d" text-anchor="%s" '
        'fill="%s">%s</text>' % (x, y, FONT, size, anchor, color, text)
    )


def _trunc(name):
    return name if len(name) <= 17 else name[:16] + "~"


def _io_badge(x, y):
    return (
        '<g class="io-badge"><rect x="%d" y="%d" width="22" height="12" '
        'rx="3" fill="#343a40"/>%s</g>'
        % (x, y, _label(x + 11, y + 9, "IO", size=7, color="#ffffff"))
    )


def render_svg(graph, placement):
    geo = _Geometry(graph, placement)
    nodes = {n.id: n for n in graph.nodes}
    entry = graph.meta["entry_point"]
    mcolors = module_colors(graph)
    vcolors = var_colors(graph)
    pvars = producer_vars(graph)
    markers = _Markers()
    edges, shapes, legends = [], [], []

    for edge in graph.call_edges:
        caller, callee = edge.caller, edge.callee
        if caller not in geo.col or callee not in geo.col:
            continue
        # the call: down from the caller into the callee
        run = geo.top(callee) - 30
        edges.append(_path(
            "call-edge",
            "M %d %d V %d H %d V %d" % (
                geo.cx(caller) - 8, geo.bottom(caller), run,
                geo.cx(callee) - 8, geo.top(callee),
            ),
            CALL_COLOR, markers, width=1.2,
        ))
        node = nodes[callee]
        if not node.returns_value:
            continue
        var = pvars.get(callee, "")
        color = vcolors.get(var, ANON_COLOR) if var else ANON_COLOR
        if node.is_dead:
            # the value never reaches the caller
            stub_end = geo.top(callee) - 26
            edges.append(_path(
                "stub",
                "M %d %d V %d" % (geo.cx(callee) + 8, geo.top(callee), stub_end),
                DEAD_COLOR, markers, width=2.4,
            ))
            edges.append(
                '<line class="tick" x1="%d" y1="%d" x2="%d" y2="%d" '
                'stroke="%s" stroke-width="2.5"/>'
                % (geo.cx(callee) + 1, stub_end, geo.cx(callee) + 15,
                   stub_end, DEAD_COLOR)
            )
            continue
        # the return: back up to the caller that asked for it
        edges.append(_path(
            "return-edge",
            "M %d %d V %d H %d V %d" % (
                geo.cx(callee) + 8, geo.top(callee), geo.top(callee) - 14,
                geo.cx(caller) + 8, geo.bottom(caller),
            ),
            color, markers, var,
        ))

    if "unreached" in geo.band_top:
        top = geo.band_top["unreached"]
        shapes.append(
            '<line class="band-rule" x1="%d" y1="%d" x2="%d" y2="%d" '
            'stroke="%s" stroke-width="1" stroke-dasharray="6 6"/>'
            % (MARGIN - 10, top - 34, MARGIN + geo.plot_w, top - 34, MUTED)
        )
        shapes.append(_label(
            MARGIN - 10, top - 42, "never reached from %s()" % (
                nodes[entry].qualname
            ), size=10, anchor="start", color=MUTED,
        ))

    for node in sorted(nodes.values(), key=lambda n: n.id):
        if node.id not in geo.col:
            continue
        fill, border = mcolors[node.module]
        cls = "node dead" if node.is_dead else "node"
        stroke = DEAD_COLOR if node.is_dead else border
        swidth = "2.5" if node.is_dead else "1.5"
        cx, cy = geo.cx(node.id), geo.cy(node.id)
        title = "<title>%s  (%s:%d)</title>" % (
            node.id, node.file, node.lines[0]
        )
        if node.has_loop:
            shapes.append(
                '<ellipse class="%s" data-id="%s" cx="%d" cy="%d" rx="%d" '
                'ry="%d" fill="%s" stroke="%s" stroke-width="%s">%s</ellipse>'
                % (cls, node.id, cx, cy, NODE_W // 2, NODE_H // 2 + 4,
                   fill, stroke, swidth, title)
            )
        else:
            shapes.append(
                '<rect class="%s" data-id="%s" x="%d" y="%d" width="%d" '
                'height="%d" rx="6" fill="%s" stroke="%s" stroke-width="%s">'
                "%s</rect>"
                % (cls, node.id, cx - NODE_W // 2, cy - NODE_H // 2, NODE_W,
                   NODE_H, fill, stroke, swidth, title)
            )
        shapes.append(_label(cx, cy + 3, _trunc(node.qualname)))
        if node.has_io:
            shapes.append(_io_badge(cx + NODE_W // 2 - 14, geo.top(node.id) - 6))

    lx = geo.width - LEGEND_W + 10
    ly = MARGIN
    for module in sorted(mcolors):
        fill, border = mcolors[module]
        legends.append(
            '<g class="legend-module"><rect x="%d" y="%d" width="14" '
            'height="14" fill="%s" stroke="%s"/>%s</g>'
            % (lx, ly, fill, border,
               _label(lx + 22, ly + 11, module.split(".")[-1] + ".py",
                      anchor="start"))
        )
        ly += 20
    ly += 14
    for local in graph.meta.get("entry_locals", []):
        var = local["var"]
        color = vcolors[var]
        arrow = (
            '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
            'stroke-width="2" marker-end="url(#%s)"/>'
            % (lx + 7, ly + 14, lx + 7, ly, color, markers.get(color))
        )
        legends.append(
            '<g class="legend-var">%s%s</g>'
            % (arrow, _label(lx + 22, ly + 11, var, anchor="start"))
        )
        ly += 20

    body = "".join(edges) + "".join(shapes) + "".join(legends)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">'
        '<rect x="0" y="0" width="%d" height="%d" fill="#f8f9fa"/>%s%s</svg>'
        % (geo.width, geo.height, geo.width, geo.height,
           geo.width, geo.height, markers.defs(), body)
    )
