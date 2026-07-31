# CSD — Codebase Sink Diagram

**A static analysis tool that draws a Python package so that structurally useless code is visually obvious.**

Dead code hides in a diff. It can't hide in a picture where every value has to visibly land somewhere.

CSD reads a package with `ast`, works out where each function's return value actually *goes*, and renders the result as an SVG under a simple metaphor: **data falls downward**. Producers sit above consumers. A value that flows onward keeps falling toward `OUTPUT`. A value nobody consumes dead-ends in a red stub with nothing below it.

No LLM calls. No network. No heuristics that require judgment. Everything is derived deterministically from the AST — and anything that *can't* be resolved statically is counted and reported, never guessed.

---

## Contents

- [The honesty counter](#the-honesty-counter)
- [Requirements](#requirements)
- [Usage](#usage)
- [Reading the diagram](#reading-the-diagram)
- [What makes a node "dead"](#what-makes-a-node-dead)
- [graph.json](#graphjson)
- [What this tool refuses to do](#what-this-tool-refuses-to-do)
- [Architecture](#architecture)
- [Specimens](#specimens)
- [Development](#development)
- [Known rough edges](#known-rough-edges)

---

## The honesty counter

`analyze` prints exactly three lines, and nothing else:

```
resolved 17
unresolved_dynamic 20
external 16
```

Every single `ast.Call` node in the package lands in exactly one of those three buckets, and the three numbers are asserted to sum to the total call count. This is deliberate and it is the most important output of the tool.

A diagram built on 60% of the edges is a diagram that lies. If a large share of your calls are `unresolved_dynamic`, the picture is telling you less than it appears to — and now you know that, instead of being quietly misled.

## Requirements

Python 3 and nothing else. No dependencies, no install step, no virtualenv required.

Developed and tested on CPython 3.12. The code targets 3.8+, but only 3.12 is exercised by the test suite. Note that the parser is your own interpreter — to analyze a package containing `match` statements you need 3.10+.

## Usage

Two subcommands with a JSON file between them:

```bash
python -m csd analyze <package_path> -o graph.json
```

```bash
python -m csd render graph.json -o diagram.svg
```

| Flag | Applies to | Meaning |
|---|---|---|
| `-o`, `--output` | both | Output path (required) |
| `--entry` | `analyze` | Fully-qualified id of the entry function, e.g. `pkg.main.main` |

**Entry point discovery**, in precedence order: `--entry` if given → a single function named `main()` → the body of an `if __name__ == "__main__":` guard. If none of these resolve — or if several `main()`s exist — it fails loudly rather than picking one.

Errors print as `csd: error: <message>` on stderr with exit code 1. `analyze` writes nothing to stdout but the three counters; `render` is silent on success.

## Reading the diagram



| Element | Meaning |
|---|---|
| **X position** | Call order — depth-first from the entry point, visiting call sites in source order. Unreached functions are appended at the right, unflagged. |
| **Y position** | Dataflow rank within each half. Producers are always drawn above their consumers, so values fall. Functions with no followable value sit in the row nearest the bus. |
| **The bus** | The entry function (`main()`), drawn full-width. Everything else hangs above or below it. |
| **Above the bus** | Everything that isn't part of the output chain — typically input, parsing, and enrichment. |
| **Below the bus** | The output chain: walk back from the value main finally prints, plus those functions' helper subtrees. |
| **Colored edge** | A value you can follow, colored per variable. A value that passes through a local in `main` lands on the bus and re-emerges — main is visibly the middleman, not a direct caller. |
| **Grey edge** | A call whose value story is invisible: discarded void results, values read only inside a condition, results consumed by an unresolved call. A grey arrow means "something happens here the analyzer can't follow." |
| **Red outline + red stub** | A dead node: it returns a value and nothing ever consumes it. The stub is that value dead-ending on the bus. |
| **Ellipse** | The function's own body contains a `for`/`while` loop. |
| **`IO` badge** | The function directly touches `open`, `print`, `input`, `sys.argv/stdin/stdout/stderr`, `os.environ`, `.read`, `.write`, `socket`, or `subprocess`. |
| **Lanes** | At each node, outgoing values leave on the right side of its column, incoming values arrive on the left — so a node's inputs and outputs never overlap. |
| **Legends** | Module colors top-right; below them, the colors of the values that cross the bus. |

## What makes a node "dead"

A node gets the red outline when **all four** of these hold:

1. it returns a value on some path, **and**
2. that value is consumed nowhere, **and**
3. the function's own body performs no direct I/O, **and**
4. it is actually called from a function (unreached code is never flagged — the tool won't accuse what it hasn't traced).

Condition 3 is why a function whose result is discarded but which `print`s stays green: the call still has an observable effect, so discarding its return isn't pointless.

**Red means "interrogate," not "delete."** Two honest false positives exist by construction:

- **In-place mutation.** A function that mutates its argument *and* returns it will look dead if the caller ignores the return value, even though the mutation is load-bearing.
- **Raise-as-gate validators.** A validator that raises on bad input and returns a value otherwise is fine to call for effect — but the analyzer tracks values, not exceptions, so it glows red.

Both are cheap to check by eye, and neither is guessed away.

## graph.json

The analyze/render boundary. Layout-free by design: it describes the program, never pixels, so other consumers (an editor extension, a CI check) can use the same file.

```jsonc
{
  "meta": {
    "tool_version": "0.1.0",
    "entry_point": "pkg.main.main",
    "resolution": { "resolved": 17, "unresolved_dynamic": 20, "external": 16 },
    "entry_locals": [                       // main's tracked locals, in bind order
      { "var": "rows", "producer": "pkg.ingest.load", "status": "consumed" },
      { "var": "trail", "producer": "pkg.audit.build", "status": "discarded" }
    ]
  },
  "nodes": [{
    "id": "pkg.util.compute_checksum",      // module-qualified, unique
    "qualname": "compute_checksum",         // dotted within the module (Class.method)
    "module": "pkg.util",
    "file": "pkg/util.py",
    "lines": [12, 18],                      // [first, last]
    "params": ["records"],
    "call_order": 7,
    "has_io": false,
    "has_loop": true,
    "returns_value": true,
    "is_terminal": true,                    // some call site discards its result
    "is_dead": true
  }],
  "call_edges":     [{ "caller": "...", "callee": "...", "line": 14 }],
  "dataflow_edges": [{ "producer": "...", "consumer": "...", "var": "rows",
                       "line": 14, "consumed_by": "call" }]
}
```

`consumed_by` is one of `call` (passed to a resolved call), `external_call` (read by a stdlib/third-party call), or `return` (returned from the enclosing function). Output is deterministic — same input, byte-identical JSON — and a committed golden file locks it.

## What this tool refuses to do

This list is the point of the tool, not an apology for it.

- **Dynamic dispatch is never guessed.** `getattr`, functions passed as arguments, dict-based dispatch tables, decorators that replace the callee, monkeypatching, and inherited-method calls via `self` all land in `unresolved_dynamic` and are counted in the number you see printed.
- **Recursion is not handled.** Any cycle in the call graph reachable from the entry point exits with a clear message rather than rendering something misleading.
- **Dataflow cycles are not handled.** If values circle within one half of the diagram, it exits rather than inventing a vertical order.
- **Deadness is one hop.** A function whose only consumer is itself dead is *not* transitively flagged yet.
- **Module-level scope isn't dataflow-analyzed**, so a value consumed at module level (`CONFIG = load_config()`) can't be proven dead — and is therefore never flagged. Conservative on purpose.
- **`params` records plain positional parameters only** — `*args`, `**kwargs`, and keyword-only parameters are omitted from the JSON. They don't affect the diagram.
- **Nothing is silently dropped.** If it can't be resolved, it gets counted as unresolved. That's the whole contract.

## Architecture

One module per pipeline stage, standard library only:

```
csd/
  schema.py      # graph.json data model + CsdError — the ONLY shared module
  symbols.py     # 1a  symbol table (qualnames, spans, params, loops, returns)
  callgraph.py   # 1b  call resolution + the three bucket counters
  callorder.py   # 1c  entry discovery + DFS call order (cycles raise)
  dataflow.py    # 1d  consumption analysis — the core
  iotags.py      # 1e  direct I/O tagging (IO_MARKERS is the one config constant)
  deadness.py    # 1f  one-hop deadness
  layout.py      # 2a  LayoutStrategy interface + BusLayout
  render.py      # 2b  hand-emitted SVG (no graph/layout libraries)
  cli.py         # the two subcommands
```

**The analyze/render seam is real.** `layout.py` and `render.py` import exactly one thing from the project — `CsdError` from `schema.py` — and nothing else. The render side literally cannot read your source code; it only ever sees the JSON. (Verify it yourself: import only `csd.schema`, `csd.layout`, `csd.render`, load a `graph.json`, and render it with zero analysis modules loaded.)

**Alternative layouts are a drop-in.** `LayoutStrategy.layout(graph) -> {node_id: (side, rank)}` takes the graph and returns placement. `BusLayout` is one implementation; a new strategy gets the `Graph` and nothing else, so it can't cheat by re-reading source.

## Specimens

`specimen/` is a small transaction categorizer with one planted dead function (`compute_checksum` — a checksum computed and immediately discarded). It's the acceptance subject for the test suite and its full analysis output is locked by `tests/golden/specimen_graph.json`.

```bash
python -m csd analyze specimen -o graph.json && python -m csd render graph.json -o diagram.svg
```

## Development

```bash
python -m unittest -v
```

84 tests, `unittest` only — no pytest, no plugins. Coverage includes per-stage unit tests on inline source fixtures, an invariant test asserting the three counters sum to the total `ast.Call` count, a golden-file regression on the whole analyze output, and structural assertions on the emitted SVG (element counts, the dead node's identity, no overlapping value lanes).

## Known rough edges

Honest v1 limitations, none of which affect the specimens:

- **Horizontal sprawl.** X is one column per function, so a few hundred functions produce a very wide SVG. Compressing X is the natural job for a second `LayoutStrategy`.
- **Reverse bus crossings.** A value produced below the bus and consumed above it draws its segments through the bus bar rather than terminating on its near edge.
- **Dead-stub geometry** assumes the dead function is called directly by the entry point; a dead call nested deeper still turns red, but its stub routing is naive.
- **`is_terminal`** is also set for functions with no return value whose call result is discarded, which is a slight drift from the field's stated meaning. JSON-only; it doesn't affect rendering.

---

Built as a rough first version, deliberately: it prefers crashing loudly over quietly handling an edge case.
