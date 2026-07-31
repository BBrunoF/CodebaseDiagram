# CSD (Codebase Sink Diagram) — Python prototype v1 design

Date: 2026-07-31
Status: approved by Bruno (see Decision log)
Source requirements: project CLAUDE.md + hand-drawn Excalidraw mockup of the target SVG.

## Goal

A deterministic static-analysis CLI that renders a Python package as an SVG designed to
make structurally useless code visually obvious. No LLM calls, no network, no judgment
heuristics. Everything derives from the AST; anything unresolvable statically is recorded
as unresolved, never guessed. Rough v1: crash loudly on unhandled cases.

## Decision log (from mockup Q&A)

| # | Question | Decision |
|---|----------|----------|
| 1 | White full-width middle band | It is `main()` rendered as a full-width horizontal bus |
| 2 | Which callees go above vs below the bus | Output-chain-tail rule (below: unbroken value-handoff chain into main's output sink + those functions' helper subtrees; above: everything else) |
| 3 | X-axis direction | call_order left → right (spec as written) |
| 4 | INPUT / OUTPUT bars | Decorative frame only; no edges touch them; IO shown as node badges |
| 5 | Code structure | `csd/` package, one module per pipeline stage, `python -m csd` |
| 6 | Circle nodes in mockup | Meaningful: ellipse = function body contains a loop (`has_loop`) |
| 7 | Specimen helper placement | `parse_amount`, `clean_text`, `normalize_merchant` live in `util.py` |
| 8 | Dataflow color legend scope | Bus-crossing variables only |

## Architecture

```
csd/
  __main__.py     # python -m csd
  cli.py          # argparse: analyze / render subcommands
  symbols.py      # stage 1a symbol table
  callgraph.py    # stage 1b call edges + resolution buckets
  callorder.py    # stage 1c DFS call order
  dataflow.py     # stage 1d consumption analysis, terminal marking
  iotags.py       # stage 1e IO_MARKERS constant + tagger
  deadness.py     # stage 1f one-hop dead rule
  schema.py       # dataclasses <-> graph.json (load/dump, tool_version)
  layout.py       # LayoutStrategy protocol + BusLayout implementation
  render.py       # hand-emitted standalone SVG
specimen/         # the test-subject package (see below)
tests/            # unittest
```

CLI contract:

```
csd analyze <package_path> -o graph.json    # prints ONLY the three resolution counters
csd render  graph.json -o diagram.svg
```

`graph.json` is the sole boundary between the stages; a future VS Code extension consumes
the same file. Analysis and render never import each other's internals — both import
`schema.py` only.

Error policy: call-graph cycle, dataflow cycle, zero or multiple entry-point candidates
(without `--entry`), unparseable file ⇒ raise a clear exception, non-zero exit. No
fallbacks, no partial output.

## Analysis rules (all deterministic)

### 1a. Symbol table
Walk every `.py` file under the package path. Record every `FunctionDef` /
`AsyncFunctionDef` and every method: qualified name (`module.Class.method` /
`module.func`), module, file, line span, parameter names, `returns_value` (any `return`
with a value on any path; a bare `return`/no return ⇒ false).

### 1b. Call graph + resolution buckets
Resolve only: direct name calls to module-local or package-imported functions;
`module.func` attribute calls where `module` is an imported analyzed module;
`self.method` within a class. Every `ast.Call` node in analyzed source lands in exactly
one bucket:

- `resolved` — callee is a function in the symbol table.
- `external` — callee name traces to an import from outside the analyzed package
  (stdlib or third-party), including builtins like `print`/`open`.
- `unresolved_dynamic` — everything else (getattr, calls on call results, locals holding
  functions, decorators that replace the callee, subscripts, lambdas).

Invariant: the three counters sum to the total number of `ast.Call` nodes encountered.
The counters are stored in metadata and printed as the only stdout of `analyze`.

### 1c. Call order
Entry point: a module-level function named `main` (exactly one across the package;
more than one ⇒ raise); else the body of an `if __name__ == "__main__":` block (its
calls seed the walk); else `--entry module.func` is required. DFS from the entry,
visiting call sites in source order; each function gets the index of its first visit.
Unreached functions are appended afterward in source order (file path asc, then line
asc) and are not flagged. A cycle in the call graph ⇒ raise.

### 1d. Dataflow (the core)
For each resolved call, the returned value is **consumed** if the result is used
directly inside a larger expression (argument, condition, return value, binop, etc.) or
bound to a name that is read later in the enclosing scope. Bound but never read, or used
as a bare expression statement ⇒ the call is **terminal**.

Producer→consumer edges skip plumbing: when a scope binds `x = f(...)` and later passes
`x` into resolved call `g(x)`, the edge is `f -> g` carrying variable name `x`. Each
dataflow edge carries `consumed_by`, exactly one of: `"call"` (flows into another
resolved call), `"external_call"` (read by an external call, e.g. `print(x)` — the edge
consumer is the enclosing function), `"return"` (returned by the enclosing function —
consumer is the enclosing function). A discarded value emits no dataflow edge; the
producing call site is terminal. Each dataflow edge records: producer node, consumer node,
variable name (`""` for direct expression use), and the consuming line.

Multiple bindings/reassignment: track per-name last-producer within straight-line
statement order of the scope body (no branch-sensitive analysis in v1; an `if` body is
walked in source order like straight-line code).

### 1e. IO tagging
`has_io` iff the function's own body (excluding nested defs) directly references any of
the single config constant `IO_MARKERS` in `iotags.py`:
`open, print, input, sys.argv, sys.stdin, sys.stdout, sys.stderr, os.environ, .read,
.write, socket, subprocess`. Attribute markers (`.read`, `.write`) match any attribute
access with that name. No transitive propagation.

### 1f. Deadness (one hop)
`is_dead` = `returns_value` AND no dataflow edge leaves the node (its value is never
consumed anywhere) AND `has_io` is false. No transitive chains.

### has_loop (new, decision #6)
True iff the function's own body (excluding nested function/class defs) contains an
`ast.For`, `ast.AsyncFor`, or `ast.While` statement. Comprehensions do NOT count in v1.

## graph.json schema

```json
{
  "meta": {
    "tool_version": "0.1.0",
    "entry_point": "specimen.main.main",
    "resolution": {"resolved": 0, "unresolved_dynamic": 0, "external": 0},
    "entry_locals": [{"var": "summary", "producer": "specimen.summarize.build_summary",
                       "status": "consumed"}]
  },
  "nodes": [{
    "id": "specimen.util.compute_checksum",
    "qualname": "compute_checksum", "module": "specimen.util",
    "file": "specimen/util.py", "lines": [12, 18],
    "params": ["records"],
    "call_order": 7, "has_io": false, "has_loop": true,
    "returns_value": true, "is_terminal": true, "is_dead": true
  }],
  "call_edges":     [{"caller": "...", "callee": "...", "line": 0}],
  "dataflow_edges": [{"producer": "...", "consumer": "...", "var": "summary",
                      "line": 0, "consumed_by": "call"}]
}
```

No layout data in the JSON. (`is_terminal` on a node = at least one call site discarded
this function's return value; the per-edge story lives in `dataflow_edges`.)

`meta.entry_locals` lists the entry function's tracked locals in bind order — one
`{"var", "producer", "status": "consumed"|"discarded"}` entry per binding — and feeds the
render side's variable legend and dead-stub colors.

## Layout (BusLayout behind LayoutStrategy)

`LayoutStrategy`: takes the loaded graph, returns `{node_id: (side, rank)}` where side ∈
{`above`, `bus`, `below`}. One implementation in v1; drop-in replacements later.

1. **Bus** — the entry function renders as a full-canvas-width horizontal bar at the
   vertical center. White fill = its module color (main.py is white in the palette).
2. **Split (output-chain-tail)** — from main's body, find the output sink: the last
   external IO call in main consuming a tracked local (`print(text)`), or main's
   `return`. Walk the value-handoff chain backward from it (`text ← render_report ←
   summary ← build_summary`). Chain members + every function reachable from them via
   call edges (their helper subtrees) ⇒ `below`. Every other reached function ⇒ `above`.
   A discarded value (dead call) is never part of the chain, so its producer stays
   above. If main has no output sink, everything is `above`. A function reachable from
   both halves' call trees goes `below` — chain reachability wins; the assignment stays
   deterministic.
3. **Ranks** — one rule for both halves: rank increases along dataflow direction
   (producer strictly above consumer), computed as longest-path order over the half's
   dataflow subgraph. Above half: sources (ultimate producers, e.g. `read_lines`,
   `normalize_merchant`) at the top near INPUT, ranks descending into the bus. Below
   half: sources (`total_by_category`, the `format_*` helpers) start just under the bus
   at rank 0, then `grand_total` at rank 1, `build_summary` at rank 2, and
   `render_report` at rank 3, descending toward OUTPUT. The only sanctioned
   against-gravity edges are below-half values returning to the bus (e.g. `text`),
   drawn as explicit up-arrows.
   Nodes with no dataflow edges in their half sit at that half's rank nearest the bus.
   All ties broken by call_order. Dataflow cycle ⇒ raise.
4. **X** = `call_order`, left → right, fixed column width; the bus spans all columns.

## Render

Standalone hand-emitted SVG, no libraries, system sans-serif.

- Frame: INPUT bar full-width at top, OUTPUT bar full-width at bottom, decorative only.
- Nodes: rounded rects 110×34; ellipse instead iff `has_loop`. Fill = module color from
  a fixed pastel palette assigned to sorted module names (stable per run and across runs
  of the same package); 1.5px darker border. Module legend top-right.
- Dead nodes: 2.5px red (#e03131) outline overriding the module border.
- `has_io`: small "IO" corner badge (rounded tag, dark fill, white text).
- Call edges: grey, thin, drawn under dataflow edges; elbow (orthogonal) routing from
  caller bottom to callee top (or looping out of the bus for main's calls).
- Dataflow edges: 2px, color per variable name from a fixed palette assigned in
  (producer call_order, var name) order; arrowheads point along the flow.
  - Bus-crossing values land on the bus and re-emerge below it (visible pass-through).
  - Value consumed inside main (`print(text)`): stub ending ON the bus with a flat ⊥
    terminator in the variable's color.
  - Discarded value (dead producer): red stub with ⊥ terminator dead-ending on the bus.
    Discarded values have no dataflow edge, so the renderer synthesizes this stub from
    the node's `is_dead`/`is_terminal` flags plus the call edge from the entry function.
- Right-edge legend: one colored arrow + variable name per bus-crossing variable only —
  defined as the variables bound in the entry function's scope that carry resolved-call
  values (specimen: `transactions`, `categorized`, `integrity`, `summary`, `text`).

## Specimen package

A small transaction categorizer whose shape matches the mockup:

- `ingest.py` — `read_lines` (open/.read ⇒ has_io), `parse_line`, `load_transactions`
  (has_loop).
- `util.py` — `clean_text`, `parse_amount`, `normalize_merchant`, `compute_checksum`
  (has_loop; **the planted slop**).
- `categorize.py` — `assign_category`, `categorize_all` (has_loop).
- `summarize.py` — `total_by_category`, `grand_total`, `build_summary`.
- `report.py` — `format_header`, `format_rows` (has_loop), `format_footer`,
  `render_report`.
- `main.py` — `main()`:
  `transactions = load_transactions(path)` → `categorized =
  categorize_all(transactions)` → `integrity = compute_checksum(categorized)` **(never
  read again)** → `summary = build_summary(categorized)` → `text =
  render_report(summary)` → `print(text)`.

Expected verdicts: `compute_checksum` is_dead (red outline + red stub on the bus);
everything else alive; `read_lines` and `main` has_io; above half = ingest + categorize
+ util reached helpers + compute_checksum; below half = build_summary, render_report and
their helper subtrees (summarize + report modules).

## Testing

`unittest`, run via `python -m unittest`. TDD during implementation.

- Per-stage unit tests on small inline source fixtures (tmp dirs).
- Resolution invariant: counters sum to total Call nodes.
- Golden test: analyze specimen ⇒ compare against committed expected `graph.json`
  (normalized).
- Layout tests: split sides and rank ordering for the specimen graph.
- SVG smoke: well-formed XML; one shape per node; ellipse count = has_loop count; dead
  node carries red outline; stub markers present; legends present.
- CLI test: `analyze` stdout is exactly three counter lines.

## Acceptance (deliverable)

1. `python -m csd analyze specimen -o graph.json` works and prints the three resolution
   counters, nothing else.
2. `python -m csd render graph.json -o diagram.svg` emits the SVG implementing every
   rule above.
3. The specimen SVG visibly shows the dead `compute_checksum` (red outline, red ⊥ stub
   on the bus).
4. All tests green.

## Out of scope (v1)

Dynamic dispatch, getattr, higher-order functions, decorators replacing callees,
monkeypatching, transitive deadness, transitive IO, recursion/cycles (raise), comprehension
loops for has_loop, branch-sensitive dataflow, other languages, VS Code extension.
