"""Stage 2 render: hand-emitted standalone SVG. No graph/layout libraries.

An icicle chart of the call tree, read as a successful run:

  - A function is a bar. Its width is everything it exclusively owns, so
    the entry point spans the whole run and a leaf is one column wide.
  - A bar sitting inside another bar IS the call. No arrow says it.
  - Colored arrows coming back up are the values those calls returned.
  - A discarded value never gets home: its return stops in a red stub.
  - A call that containment cannot express — a helper shared by two
    callers, owned by neither — keeps an explicit grey arrow.

Emit conventions (tests depend on them): class is always the first
attribute; nodes carry data-id; return arrows carry data-var.
"""
from .schema import CsdError

COL_W = 132
BAR_H = 30
ROW_H = 68
BAR_GAP = 6
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
CALL_COLOR = "#868e96"
TEXT = "#212529"
MUTED = "#868e96"
FONT = 'font-family="sans-serif"'
LOOP_MARK = "&#8635; "


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
    def __init__(self, graph, placement):
        known = {n.id for n in graph.nodes}
        bands = {}
        for nid, slot in placement.items():
            if nid not in known:
                raise CsdError("placement names unknown node %s" % nid)
            bands.setdefault(slot[0], []).append(nid)
        self.placement = placement
        self.band_top = {}
        widest = 0
        top = MARGIN
        for band in ("reached", "unreached"):
            group = bands.get(band)
            if not group:
                continue
            self.band_top[band] = top
            rows = max(placement[nid][1] for nid in group) + 1
            widest = max(widest, max(
                placement[nid][2] + placement[nid][3] for nid in group
            ))
            top += rows * ROW_H + BAND_GAP
        self.plot_w = widest * COL_W
        self.width = MARGIN * 2 + self.plot_w + LEGEND_W
        self.height = top - BAND_GAP + MARGIN

    def x(self, nid):
        return MARGIN + self.placement[nid][2] * COL_W

    def w(self, nid):
        return self.placement[nid][3] * COL_W - BAR_GAP

    def y(self, nid):
        band, degree = self.placement[nid][0], self.placement[nid][1]
        return self.band_top[band] + degree * ROW_H

    def bottom(self, nid):
        return self.y(nid) + BAR_H

    def contains(self, outer, inner):
        _, _, ocol, ospan = self.placement[outer]
        _, _, icol, ispan = self.placement[inner]
        return ocol <= icol and icol + ispan <= ocol + ospan


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


def _label(x, y, text, size=10, anchor="start", color=TEXT):
    return (
        '<text x="%d" y="%d" %s font-size="%d" text-anchor="%s" '
        'fill="%s">%s</text>' % (x, y, FONT, size, anchor, color, text)
    )


def _fit(name, width, marked):
    room = max(1, int((width - 16) / 5.9))
    if marked:
        room -= 2
    if len(name) > room:
        name = name[: max(1, room - 1)] + "~"
    return (LOOP_MARK if marked else "") + name


def _io_badge(x, y):
    return (
        '<g class="io-badge"><rect x="%d" y="%d" width="22" height="12" '
        'rx="3" fill="#343a40"/>%s</g>'
        % (x, y, _label(x + 4, y + 9, "IO", size=7, color="#ffffff"))
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
        if caller not in placement or callee not in placement:
            continue
        node = nodes[callee]
        inside = geo.contains(caller, callee)
        if not inside:
            # containment cannot say this call: draw it
            edges.append(_path(
                "call-edge",
                "M %d %d V %d H %d V %d" % (
                    geo.x(caller) + 24, geo.bottom(caller), geo.y(callee) - 24,
                    geo.x(callee) + geo.w(callee) // 2, geo.y(callee),
                ),
                CALL_COLOR, markers, width=1.2,
            ))
        if not node.returns_value:
            continue
        var = pvars.get(callee, "")
        color = vcolors.get(var, ANON_COLOR) if var else ANON_COLOR
        if node.is_dead:
            stop = geo.y(callee) - 22
            edges.append(_path(
                "stub",
                "M %d %d V %d" % (geo.x(callee) + 14, geo.y(callee), stop),
                DEAD_COLOR, markers, width=2.4,
            ))
            edges.append(
                '<line class="tick" x1="%d" y1="%d" x2="%d" y2="%d" '
                'stroke="%s" stroke-width="2.5"/>'
                % (geo.x(callee) + 7, stop, geo.x(callee) + 21, stop,
                   DEAD_COLOR)
            )
            continue
        if inside:
            # straight up into the bar that owns it
            edges.append(_path(
                "return-edge",
                "M %d %d V %d" % (
                    geo.x(callee) + 14, geo.y(callee), geo.bottom(caller)
                ),
                color, markers, var,
            ))
        else:
            edges.append(_path(
                "return-edge",
                "M %d %d V %d H %d V %d" % (
                    geo.x(callee) + geo.w(callee) // 2 + 12, geo.y(callee),
                    geo.y(callee) - 10, geo.x(caller) + 40,
                    geo.bottom(caller),
                ),
                color, markers, var,
            ))

    if "unreached" in geo.band_top:
        top = geo.band_top["unreached"]
        shapes.append(
            '<line class="band-rule" x1="%d" y1="%d" x2="%d" y2="%d" '
            'stroke="%s" stroke-width="1" stroke-dasharray="6 6"/>'
            % (MARGIN, top - 34, MARGIN + geo.plot_w, top - 34, MUTED)
        )
        shapes.append(_label(
            MARGIN, top - 42,
            "never reached from %s()" % nodes[entry].qualname,
            size=10, color=MUTED,
        ))

    for node in sorted(nodes.values(), key=lambda n: n.id):
        if node.id not in placement:
            continue
        fill, border = mcolors[node.module]
        cls = "node dead" if node.is_dead else "node"
        stroke = DEAD_COLOR if node.is_dead else border
        swidth = "2.5" if node.is_dead else "1.2"
        x, y, w = geo.x(node.id), geo.y(node.id), geo.w(node.id)
        shapes.append(
            '<rect class="%s" data-id="%s" x="%d" y="%d" width="%d" '
            'height="%d" rx="4" fill="%s" stroke="%s" stroke-width="%s">'
            "<title>%s  (%s:%d)</title></rect>"
            % (cls, node.id, x, y, w, BAR_H, fill, stroke, swidth,
               node.id, node.file, node.lines[0])
        )
        shapes.append(
            _label(x + 8, y + 19, _fit(node.qualname, w, node.has_loop))
        )
        if node.has_io:
            shapes.append(_io_badge(x + w - 26, y - 6))

    lx = geo.width - LEGEND_W + 10
    ly = MARGIN
    for module in sorted(mcolors):
        fill, border = mcolors[module]
        legends.append(
            '<g class="legend-module"><rect x="%d" y="%d" width="14" '
            'height="14" fill="%s" stroke="%s"/>%s</g>'
            % (lx, ly, fill, border,
               _label(lx + 22, ly + 11, module.split(".")[-1] + ".py"))
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
            % (arrow, _label(lx + 22, ly + 11, var))
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
