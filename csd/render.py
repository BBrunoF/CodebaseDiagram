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
import colorsys

from .schema import CsdError

COL_W = 132
BAR_H = 30
ROW_H = 68
BAR_GAP = 6
MARGIN = 40
BAND_GAP = 84
LEGEND_ROW_H = 20
LEGEND_COL_W = 176
LEGEND_PAD = 30
# a bar is its own execution left to right: the call arrives at the start,
# the return leaves from the end
LANE_INSET = 13

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


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb)


def _spread_palette(count):
    """Hues stepped by the golden ratio, so any number of modules stays
    distinguishable instead of cycling a fixed list."""
    palette = []
    for i in range(count):
        hue = (i * 0.6180339887498949) % 1.0
        palette.append((
            _hex(colorsys.hls_to_rgb(hue, 0.84, 0.62)),
            _hex(colorsys.hls_to_rgb(hue, 0.40, 0.62)),
        ))
    return palette


def module_colors(graph):
    entry_module = graph.meta["entry_point"].rsplit(".", 1)[0]
    modules = sorted({n.module for n in graph.nodes})
    others = [m for m in modules if m != entry_module]
    palette = (
        MODULE_PALETTE if len(others) <= len(MODULE_PALETTE)
        else _spread_palette(len(others))
    )
    colors, i = {}, 0
    for module in modules:
        if module == entry_module:
            colors[module] = ENTRY_FILL
        else:
            colors[module] = palette[i]
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


def argument_vars(graph):
    """{(callee, call line): the name of the value handed to that call}."""
    passed = {}
    for edge in sorted(graph.dataflow_edges, key=lambda e: (e.line, e.var)):
        if edge.consumed_by == "call" and edge.var:
            passed.setdefault((edge.consumer, edge.line), edge.var)
    return passed


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
        self.plot_h = top - BAND_GAP + MARGIN

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
    argvars = argument_vars(graph)
    markers = _Markers()
    edges, shapes, legends = [], [], []

    for edge in graph.call_edges:
        caller, callee = edge.caller, edge.callee
        if caller not in placement or callee not in placement:
            continue
        node = nodes[callee]
        inside = geo.contains(caller, callee)
        enters = geo.x(callee) + LANE_INSET
        leaves = geo.x(callee) + geo.w(callee) - LANE_INSET
        # the call carries an argument in; colour it by that value when the
        # analyzer can name it, otherwise leave it grey
        arg = argvars.get((callee, edge.line))
        arg_color = vcolors.get(arg, CALL_COLOR) if arg else CALL_COLOR
        if inside:
            # the callee sits under its caller's bar: drop straight in
            call_d = "M %d %d V %d" % (
                enters, geo.bottom(caller), geo.y(callee)
            )
        else:
            # a helper owned by neither caller: reach out to it
            call_d = "M %d %d V %d H %d V %d" % (
                geo.x(caller) + 24, geo.bottom(caller), geo.y(callee) - 24,
                enters, geo.y(callee),
            )
        edges.append(_path(
            "call-edge", call_d, arg_color, markers, arg, width=1.4
        ))
        if not node.returns_value:
            continue
        var = pvars.get(callee, "")
        color = vcolors.get(var, ANON_COLOR) if var else ANON_COLOR
        if node.is_dead:
            stop = geo.y(callee) - 22
            edges.append(_path(
                "stub",
                "M %d %d V %d" % (leaves, geo.y(callee), stop),
                DEAD_COLOR, markers, width=2.4,
            ))
            edges.append(
                '<line class="tick" x1="%d" y1="%d" x2="%d" y2="%d" '
                'stroke="%s" stroke-width="2.5"/>'
                % (leaves - 7, stop, leaves + 7, stop, DEAD_COLOR)
            )
            continue
        if inside:
            # straight back up into the bar that called it
            edges.append(_path(
                "return-edge",
                "M %d %d V %d" % (leaves, geo.y(callee), geo.bottom(caller)),
                color, markers, var,
            ))
        else:
            edges.append(_path(
                "return-edge",
                "M %d %d V %d H %d V %d" % (
                    leaves, geo.y(callee), geo.y(callee) - 10,
                    geo.x(caller) + 40, geo.bottom(caller),
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

    # the legend wraps into as many columns as it needs, so a package with
    # dozens of modules never pushes rows off the bottom of the canvas
    entries = [
        ("module", module.split(".")[-1] + ".py", mcolors[module])
        for module in sorted(mcolors)
    ]
    entries += [
        ("var", local["var"], vcolors[local["var"]])
        for local in graph.meta.get("entry_locals", [])
    ]
    per_column = max(1, (geo.plot_h - MARGIN * 2) // LEGEND_ROW_H)
    columns = max(1, -(-len(entries) // per_column))
    legend_x = MARGIN + geo.plot_w + LEGEND_PAD
    width = legend_x + columns * LEGEND_COL_W + MARGIN
    height = max(
        geo.plot_h,
        MARGIN * 2 + min(len(entries), per_column) * LEGEND_ROW_H,
    )

    for index, (kind, text, color) in enumerate(entries):
        lx = legend_x + (index // per_column) * LEGEND_COL_W
        ly = MARGIN + (index % per_column) * LEGEND_ROW_H
        if kind == "module":
            fill, border = color
            swatch = (
                '<rect x="%d" y="%d" width="14" height="14" fill="%s" '
                'stroke="%s"/>' % (lx, ly, fill, border)
            )
        else:
            swatch = (
                '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" '
                'stroke-width="2" marker-end="url(#%s)"/>'
                % (lx + 7, ly + 14, lx + 7, ly, color, markers.get(color))
            )
        legends.append(
            '<g class="legend-%s">%s%s</g>'
            % (kind, swatch, _label(lx + 22, ly + 11, text))
        )

    body = "".join(edges) + "".join(shapes) + "".join(legends)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">'
        '<rect x="0" y="0" width="%d" height="%d" fill="#f8f9fa"/>%s%s</svg>'
        % (width, height, width, height, width, height,
           markers.defs(), body)
    )
