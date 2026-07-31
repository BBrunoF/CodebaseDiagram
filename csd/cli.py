"""CLI and the analyze-side orchestration.

The analyze subcommand's stdout is EXACTLY the three resolution counters.
"""
import argparse
import json
import sys

from . import callgraph, callorder, dataflow, deadness, iotags, schema, symbols


def analyze_package(package_path, entry_override=None):
    modules = symbols.discover_modules(package_path)
    symtab = symbols.build_symbol_table(modules)
    sites, counters = callgraph.analyze_calls(modules, symtab)
    resolved_sites = [s for s in sites if s.bucket == "resolved" and s.callee]
    entry_id, seeds = callorder.find_entry(symtab, modules, sites, entry_override)
    order = callorder.assign_call_order(symtab, resolved_sites, entry_id, seeds)
    edges, consumed, terminal_sites, journal = dataflow.analyze_dataflow(
        symtab, sites
    )
    nodes = {}
    for f in symtab.values():
        nodes[f.id] = schema.Node(
            id=f.id, qualname=f.qualname, module=f.module, file=f.file,
            lines=list(f.lines), params=list(f.params),
            call_order=order[f.id],
            has_io=iotags.tag_has_io(f),
            has_loop=f.has_loop,
            returns_value=f.returns_value,
        )
    for site in terminal_sites:
        if site.callee in nodes:
            nodes[site.callee].is_terminal = True
    deadness.mark_dead(nodes, consumed, resolved_sites)
    entry_locals = [
        {
            "var": b.var,
            "producer": b.site.callee,
            "status": "consumed" if b.consumed else "discarded",
        }
        for b in journal.get(entry_id, [])
    ]
    meta = {
        "tool_version": schema.TOOL_VERSION,
        "entry_point": entry_id,
        "resolution": counters,
        "entry_locals": entry_locals,
    }
    return schema.Graph(
        meta=meta,
        nodes=[nodes[i] for i in sorted(nodes)],
        call_edges=[
            schema.CallEdge(caller=s.caller, callee=s.callee, line=s.line)
            for s in resolved_sites
            if not s.caller.startswith("<module>:")
        ],
        dataflow_edges=edges,
    )


def _cmd_analyze(args):
    graph = analyze_package(args.package_path, args.entry)
    with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(graph.to_json())
        fh.write("\n")
    for bucket in callgraph.BUCKETS:
        print("%s %d" % (bucket, graph.meta["resolution"][bucket]))
    return 0


def _cmd_render(args):
    from . import layout, render  # imported here so analyze stays render-free

    with open(args.graph, "r", encoding="utf-8") as fh:
        graph = schema.Graph.from_json(fh.read())
    placement = layout.CallTreeLayout().layout(graph)
    svg = render.render_svg(graph, placement)
    with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
        fh.write("\n")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="csd")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="analyze a package into graph.json")
    analyze.add_argument("package_path")
    analyze.add_argument("-o", "--output", required=True)
    analyze.add_argument("--entry", default=None)
    analyze.set_defaults(func=_cmd_analyze)
    rend = sub.add_parser("render", help="render graph.json to an SVG")
    rend.add_argument("graph")
    rend.add_argument("-o", "--output", required=True)
    rend.set_defaults(func=_cmd_render)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (schema.CsdError, OSError, json.JSONDecodeError, SyntaxError) as exc:
        print("csd: error: %s" % exc, file=sys.stderr)
        return 1
