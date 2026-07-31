# CSD Prototype v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `csd` CLI that statically analyzes a Python package into `graph.json` and renders it as the "main-as-bus" SVG defined in the approved spec.

**Architecture:** Pipeline of small stdlib-only modules (`symbols → callgraph → callorder → dataflow → iotags → deadness`) orchestrated by `cli.analyze_package`, writing a layout-free `graph.json`; the render side (`layout.BusLayout` behind a `LayoutStrategy` seam + `render.render_svg`) consumes only that JSON. A `specimen/` package with one planted dead function is the acceptance subject.

**Tech Stack:** Python 3 stdlib only: `ast`, `dataclasses`, `json`, `argparse`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-07-31-csd-prototype-design.md` — normative for every rule below.

## Global Constraints

- Standard library only. No pip installs, anywhere, including tests (`unittest`, not pytest).
- Deterministic output: same input ⇒ byte-identical `graph.json` (sorted keys) and SVG.
- `csd analyze` prints EXACTLY three lines to stdout (`resolved N` / `unresolved_dynamic N` / `external N`) and nothing else. `csd render` prints nothing.
- Unhandled cases (cycles, ambiguous entry, bad paths) ⇒ raise `schema.CsdError` with a clear message; CLI exits non-zero. Never guess, never silently drop.
- Every `ast.Call` lands in exactly one bucket; the three counters must sum to the total number of Call nodes.
- All commands below run from the repo root: `C:\Users\bruni\Desktop\Coding Projetcs\OutputGravityDiagramPrototype`.
- **No Windows Python exists on this machine** (only the Store stub, which fails with
  "Python was not found"). Every `python ...` command in this plan is shorthand for
  running it through WSL (Python 3.12.3) from the repo root:
  `wsl --cd "C:\Users\bruni\Desktop\Coding Projetcs\OutputGravityDiagramPrototype" python3 <args>`
  — e.g. `python -m unittest -v` means
  `wsl --cd "C:\Users\bruni\Desktop\Coding Projetcs\OutputGravityDiagramPrototype" python3 -m unittest -v`.
  Git commands run natively on Windows as usual.
- Commit after every task with the message given in its final step.

---

### Task 1: Skeleton + schema.py

**Files:**
- Create: `csd/__init__.py`, `csd/schema.py`, `tests/__init__.py`, `tests/test_schema.py`, `.gitignore`

**Interfaces:**
- Produces: `schema.TOOL_VERSION: str`; `schema.CsdError(Exception)`; dataclasses `Node(id, qualname, module, file, lines, params, call_order=-1, has_io=False, has_loop=False, returns_value=False, is_terminal=False, is_dead=False)`, `CallEdge(caller, callee, line)`, `DataflowEdge(producer, consumer, var, line, consumed_by)`; `Graph(meta, nodes, call_edges, dataflow_edges)` with `to_json() -> str` and `Graph.from_json(text) -> Graph`. Every later task imports from here.

- [ ] **Step 1: Write the failing test**

`tests/__init__.py` — empty file. `tests/test_schema.py`:

```python
import unittest

from csd import schema


def sample_graph():
    return schema.Graph(
        meta={
            "tool_version": schema.TOOL_VERSION,
            "entry_point": "pkg.main.main",
            "resolution": {"resolved": 1, "unresolved_dynamic": 2, "external": 3},
            "entry_locals": [
                {"var": "x", "producer": "pkg.a.f", "status": "consumed"}
            ],
        },
        nodes=[
            schema.Node(
                id="pkg.a.f", qualname="f", module="pkg.a", file="pkg/a.py",
                lines=[1, 3], params=["n"], call_order=1, has_io=False,
                has_loop=True, returns_value=True, is_terminal=False,
                is_dead=False,
            )
        ],
        call_edges=[schema.CallEdge(caller="pkg.main.main", callee="pkg.a.f", line=4)],
        dataflow_edges=[
            schema.DataflowEdge(
                producer="pkg.a.f", consumer="pkg.main.main", var="x",
                line=5, consumed_by="external_call",
            )
        ],
    )


class SchemaRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        graph = sample_graph()
        text = graph.to_json()
        loaded = schema.Graph.from_json(text)
        self.assertEqual(loaded, graph)

    def test_json_is_deterministic(self):
        self.assertEqual(sample_graph().to_json(), sample_graph().to_json())

    def test_csd_error_is_exception(self):
        self.assertTrue(issubclass(schema.CsdError, Exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_schema -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd'`

- [ ] **Step 3: Write minimal implementation**

`csd/__init__.py` — empty file. `.gitignore`:

```
__pycache__/
*.pyc
graph.json
diagram.svg
```

`csd/schema.py`:

```python
"""graph.json data model + shared error type.

The ONLY module both the analyze side and the render side import.
"""
import json
from dataclasses import asdict, dataclass, field

TOOL_VERSION = "0.1.0"


class CsdError(Exception):
    """Any condition v1 refuses to handle. CLI turns this into exit 1."""


@dataclass
class Node:
    id: str
    qualname: str
    module: str
    file: str
    lines: list
    params: list
    call_order: int = -1
    has_io: bool = False
    has_loop: bool = False
    returns_value: bool = False
    is_terminal: bool = False
    is_dead: bool = False


@dataclass
class CallEdge:
    caller: str
    callee: str
    line: int


@dataclass
class DataflowEdge:
    producer: str
    consumer: str
    var: str
    line: int
    consumed_by: str  # "call" | "external_call" | "return"


@dataclass
class Graph:
    meta: dict
    nodes: list = field(default_factory=list)
    call_edges: list = field(default_factory=list)
    dataflow_edges: list = field(default_factory=list)

    def to_json(self):
        return json.dumps(
            {
                "meta": self.meta,
                "nodes": [asdict(n) for n in self.nodes],
                "call_edges": [asdict(e) for e in self.call_edges],
                "dataflow_edges": [asdict(e) for e in self.dataflow_edges],
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text):
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            nodes=[Node(**n) for n in raw["nodes"]],
            call_edges=[CallEdge(**e) for e in raw["call_edges"]],
            dataflow_edges=[DataflowEdge(**e) for e in raw["dataflow_edges"]],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_schema -v`
Expected: `OK`, 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd tests .gitignore
git commit -m "feat: csd package skeleton + graph.json schema"
```

---

### Task 2: symbols.py (stage 1a)

**Files:**
- Create: `csd/symbols.py`, `tests/helpers.py`, `tests/test_symbols.py`

**Interfaces:**
- Consumes: `schema.CsdError`.
- Produces: `ModuleSource(name, file, tree)`; `FunctionInfo(id, qualname, module, file, lines, params, returns_value, has_loop, ast_node)`; `discover_modules(package_path) -> list[ModuleSource]`; `build_symbol_table(modules) -> dict[str, FunctionInfo]`; `own_body_nodes(fn_ast) -> iterator of AST nodes` (a function's own body, never descending into nested function/class defs — reused by callgraph, dataflow, iotags).
- Produces (tests): `helpers.make_package(tmp_dir, name, files: dict[str, str]) -> package path` writes a package from `{relative_filename: source}` and returns its directory.

- [ ] **Step 1: Write the failing test**

`tests/helpers.py`:

```python
import os
import textwrap


def make_package(tmp_dir, name, files):
    """Write a package named `name` under tmp_dir from {relpath: source}."""
    pkg = os.path.join(tmp_dir, name)
    os.makedirs(pkg, exist_ok=True)
    init = os.path.join(pkg, "__init__.py")
    if not os.path.exists(init):
        with open(init, "w", encoding="utf-8") as fh:
            fh.write("")
    for rel, src in files.items():
        path = os.path.join(pkg, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(src))
    return pkg
```

`tests/test_symbols.py`:

```python
import tempfile
import unittest

from csd import symbols
from tests.helpers import make_package

SRC = """
    def free(a, b):
        for _ in range(a):
            b += 1
        return b


    def void():
        print("hi")


    class Thing:
        def method(self):
            def inner():
                while True:
                    break
            return inner
"""


class SymbolTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"mod.py": SRC})
        self.modules = symbols.discover_modules(pkg)
        self.table = symbols.build_symbol_table(self.modules)

    def test_module_discovery(self):
        names = sorted(m.name for m in self.modules)
        self.assertEqual(names, ["pkg", "pkg.mod"])
        mod = [m for m in self.modules if m.name == "pkg.mod"][0]
        self.assertEqual(mod.file, "pkg/mod.py")

    def test_functions_recorded_with_qualnames(self):
        self.assertEqual(
            sorted(self.table),
            ["pkg.mod.Thing.method", "pkg.mod.Thing.method.inner",
             "pkg.mod.free", "pkg.mod.void"],
        )

    def test_flags(self):
        free = self.table["pkg.mod.free"]
        self.assertEqual(free.params, ["a", "b"])
        self.assertTrue(free.returns_value)
        self.assertTrue(free.has_loop)
        void = self.table["pkg.mod.void"]
        self.assertFalse(void.returns_value)
        self.assertFalse(void.has_loop)
        # inner's while-loop must NOT leak into method
        method = self.table["pkg.mod.Thing.method"]
        self.assertFalse(method.has_loop)
        self.assertTrue(method.returns_value)
        inner = self.table["pkg.mod.Thing.method.inner"]
        self.assertTrue(inner.has_loop)

    def test_lines_are_recorded(self):
        free = self.table["pkg.mod.free"]
        self.assertEqual(free.lines[0], 2)
        self.assertGreater(free.lines[1], free.lines[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_symbols -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.symbols'`

- [ ] **Step 3: Write minimal implementation**

`csd/symbols.py`:

```python
"""Stage 1a: the symbol table.

Walks every .py file under the package path and records every function
and method, including nested ones.
"""
import ast
import os
from dataclasses import dataclass

from .schema import CsdError

_NESTED_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass
class ModuleSource:
    name: str  # dotted module name, e.g. "specimen.util"
    file: str  # path relative to the package's parent dir, forward slashes
    tree: object  # ast.Module


@dataclass
class FunctionInfo:
    id: str
    qualname: str
    module: str
    file: str
    lines: tuple
    params: list
    returns_value: bool
    has_loop: bool
    ast_node: object  # the FunctionDef / AsyncFunctionDef


def discover_modules(package_path):
    package_path = os.path.abspath(package_path)
    if not os.path.isdir(package_path):
        raise CsdError("package path is not a directory: %s" % package_path)
    parent = os.path.dirname(package_path)
    modules = []
    for root, dirs, files in os.walk(package_path):
        dirs.sort()
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, parent).replace(os.sep, "/")
            dotted = rel[:-3].replace("/", ".")
            if dotted.endswith(".__init__"):
                dotted = dotted[: -len(".__init__")]
            elif dotted == "__init__":
                raise CsdError("package path must be a package directory")
            with open(full, "r", encoding="utf-8") as fh:
                source = fh.read()
            modules.append(
                ModuleSource(name=dotted, file=rel, tree=ast.parse(source, filename=rel))
            )
    return modules


def own_body_nodes(fn):
    """Every AST node in fn's own body, not descending into nested defs."""
    stack = list(fn.body)
    while stack:
        node = stack.pop(0)
        yield node
        if isinstance(node, _NESTED_DEFS):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _returns_value(fn):
    return any(
        isinstance(n, ast.Return) and n.value is not None
        for n in own_body_nodes(fn)
    )


def _has_loop(fn):
    return any(
        isinstance(n, (ast.For, ast.AsyncFor, ast.While))
        for n in own_body_nodes(fn)
    )


def _functions_with_qualnames(tree):
    found = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + child.name
                found.append((child, qual))
                visit(child, qual + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def build_symbol_table(modules):
    table = {}
    for mod in modules:
        for fn, qual in _functions_with_qualnames(mod.tree):
            fid = "%s.%s" % (mod.name, qual)
            if fid in table:
                raise CsdError("duplicate function id: %s" % fid)
            table[fid] = FunctionInfo(
                id=fid,
                qualname=qual,
                module=mod.name,
                file=mod.file,
                lines=(fn.lineno, fn.end_lineno),
                params=[a.arg for a in fn.args.args],
                returns_value=_returns_value(fn),
                has_loop=_has_loop(fn),
                ast_node=fn,
            )
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_symbols -v`
Expected: `OK`, 4 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd/symbols.py tests/helpers.py tests/test_symbols.py
git commit -m "feat: stage 1a symbol table with has_loop/returns_value"
```

---
### Task 3: callgraph.py (stage 1b)

**Files:**
- Create: `csd/callgraph.py`, `tests/test_callgraph.py`

**Interfaces:**
- Consumes: `symbols.ModuleSource`, `symbols.FunctionInfo`, `symbols.own_body_nodes`, `schema.CsdError`.
- Produces: `BUCKETS = ("resolved", "unresolved_dynamic", "external")`; `CallSite(caller, callee, line, bucket, call)` where `caller` is a function id or `"<module>:" + module_name`, `callee` is a function id for resolved sites else `""`, `call` is the `ast.Call` node; `analyze_calls(modules, symtab) -> (list[CallSite], dict[bucket, int])`; `dotted_name(expr) -> str | None` (renders `a.b.c` attribute chains, reused by iotags).

- [ ] **Step 1: Write the failing test**

`tests/test_callgraph.py`:

```python
import ast
import tempfile
import unittest

from csd import callgraph, symbols
from tests.helpers import make_package

FILES = {
    "util.py": """
        def helper(x):
            return x + 1
    """,
    "main.py": """
        import sys
        from . import util
        from .util import helper

        def local(n):
            return n

        def main():
            a = helper(1)
            b = util.helper(a)
            c = local(b)
            print(c)
            d = sys.stdin.read()
            unknown = getattr(util, "helper")
            unknown(d)
            return c

        if __name__ == "__main__":
            main()
    """,
}


class CallResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", FILES)
        self.modules = symbols.discover_modules(pkg)
        self.symtab = symbols.build_symbol_table(self.modules)
        self.sites, self.counters = callgraph.analyze_calls(self.modules, self.symtab)

    def resolved_pairs(self):
        return sorted(
            (s.caller, s.callee) for s in self.sites if s.bucket == "resolved"
        )

    def test_resolved_edges(self):
        self.assertEqual(
            self.resolved_pairs(),
            [
                ("<module>:pkg.main", "pkg.main.main"),   # the __main__ guard call
                ("pkg.main.main", "pkg.main.local"),
                ("pkg.main.main", "pkg.util.helper"),     # from-import call
                ("pkg.main.main", "pkg.util.helper"),     # module-attribute call
            ],
        )

    def test_buckets(self):
        # print, sys.stdin.read, getattr -> external; unknown(d) -> dynamic
        self.assertEqual(self.counters["resolved"], 4)
        self.assertEqual(self.counters["external"], 3)
        self.assertEqual(self.counters["unresolved_dynamic"], 1)

    def test_invariant_counters_sum_to_total_calls(self):
        total = sum(
            isinstance(n, ast.Call)
            for m in self.modules
            for n in ast.walk(m.tree)
        )
        self.assertEqual(sum(self.counters.values()), total)

    def test_every_site_has_exactly_one_bucket(self):
        for site in self.sites:
            self.assertIn(site.bucket, callgraph.BUCKETS)

    def test_dotted_name(self):
        expr = ast.parse("a.b.c", mode="eval").body
        self.assertEqual(callgraph.dotted_name(expr), "a.b.c")
        call = ast.parse("f()()", mode="eval").body
        self.assertIsNone(callgraph.dotted_name(call.func))


class SelfMethodCalls(unittest.TestCase):
    def test_self_method_resolves(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {"cls.py": """
            class Greeter:
                def greet(self):
                    return self.name()

                def name(self):
                    return "n"
        """})
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, counters = callgraph.analyze_calls(modules, symtab)
        resolved = [s for s in sites if s.bucket == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].caller, "pkg.cls.Greeter.greet")
        self.assertEqual(resolved[0].callee, "pkg.cls.Greeter.name")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_callgraph -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.callgraph'`

- [ ] **Step 3: Write minimal implementation**

`csd/callgraph.py`:

```python
"""Stage 1b: put every ast.Call into exactly one resolution bucket.

Resolved: direct-name calls to module-local or package-imported functions,
module.func attribute calls, self.method calls. Everything else is either
external (traces to an import from outside the package, or a builtin) or
unresolved_dynamic. No guessing.
"""
import ast
import builtins
from dataclasses import dataclass

from .schema import CsdError
from .symbols import own_body_nodes

BUCKETS = ("resolved", "unresolved_dynamic", "external")


@dataclass
class CallSite:
    caller: str  # function id, or "<module>:" + module name
    callee: str  # resolved function id, else ""
    line: int
    bucket: str
    call: object  # the ast.Call node


def dotted_name(expr):
    """Render an a.b.c attribute chain; None if the base is not a Name."""
    parts = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        parts.append(expr.id)
        return ".".join(reversed(parts))
    return None


def _import_map(mod):
    """local name -> dotted target for every import in the module."""
    imports = {}
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    imports[root] = root
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(mod.name, node)
            for alias in node.names:
                imports[alias.asname or alias.name] = base + "." + alias.name
    return imports


def _resolve_from(module_name, node):
    if node.level == 0:
        return node.module
    parts = module_name.split(".")
    base = parts[: len(parts) - node.level]
    if node.module:
        base.append(node.module)
    if not base:
        raise CsdError(
            "relative import escapes the package at %s line %d"
            % (module_name, node.lineno)
        )
    return ".".join(base)


def _classify(call, caller_class, mod_name, imports, symtab, pkg):
    func = call.func
    if isinstance(func, ast.Name):
        target = imports.get(func.id)
        if target is not None:
            if target in symtab:
                return "resolved", target
            if target.split(".")[0] == pkg:
                return "unresolved_dynamic", ""
            return "external", ""
        local = mod_name + "." + func.id
        if local in symtab:
            return "resolved", local
        if hasattr(builtins, func.id):
            return "external", ""
        return "unresolved_dynamic", ""
    if isinstance(func, ast.Attribute):
        if (
            isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and caller_class
        ):
            target = "%s.%s.%s" % (mod_name, caller_class, func.attr)
            if target in symtab:
                return "resolved", target
            return "unresolved_dynamic", ""
        dotted = dotted_name(func)
        if dotted is not None:
            root = dotted.split(".")[0]
            target = imports.get(root)
            if target is not None:
                full = target + dotted[len(root):]
                if full in symtab:
                    return "resolved", full
                if full.split(".")[0] == pkg:
                    return "unresolved_dynamic", ""
                return "external", ""
        return "unresolved_dynamic", ""
    return "unresolved_dynamic", ""


def _own_calls(fn):
    return [n for n in own_body_nodes(fn) if isinstance(n, ast.Call)]


def analyze_calls(modules, symtab):
    """Every Call node in every module, partitioned exactly once."""
    by_module = {}
    for f in symtab.values():
        by_module.setdefault(f.module, []).append(f)
    sites = []
    counters = {b: 0 for b in BUCKETS}
    for mod in modules:
        imports = _import_map(mod)
        pkg = mod.name.split(".")[0]
        functions = by_module.get(mod.name, [])
        owned = {}
        for f in functions:
            for call in _own_calls(f.ast_node):
                owned[id(call)] = f
        for call in (n for n in ast.walk(mod.tree) if isinstance(n, ast.Call)):
            f = owned.get(id(call))
            if f is not None:
                caller = f.id
                parts = f.qualname.rsplit(".", 1)
                caller_class = parts[0] if len(parts) == 2 else None
            else:
                caller = "<module>:" + mod.name
                caller_class = None
            bucket, callee = _classify(
                call, caller_class, mod.name, imports, symtab, pkg
            )
            counters[bucket] += 1
            sites.append(CallSite(caller, callee, call.lineno, bucket, call))
    return sites, counters
```

Note: `caller_class` is derived from the qualname's parent segment. That treats a
function nested directly inside a plain function the same as a method for `self.x()`
calls — the lookup then simply misses the symbol table and lands in
`unresolved_dynamic`, which is the correct bucket for it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_callgraph -v`
Expected: `OK`, 6 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd/callgraph.py tests/test_callgraph.py
git commit -m "feat: stage 1b call resolution with three-bucket counters"
```

---

### Task 4: callorder.py (stage 1c)

**Files:**
- Create: `csd/callorder.py`, `tests/test_callorder.py`

**Interfaces:**
- Consumes: `callgraph.CallSite`, `symbols.FunctionInfo`, `schema.CsdError`.
- Produces: `find_entry(symtab, modules, sites, override=None) -> (entry_id, seed_callee_ids)` — `entry_id` is a function id, or `"<module>.__main__"`-style pseudo id (`module_name + ".__main__"`) when falling back to the `if __name__ == "__main__":` guard; `seed_callee_ids` is the resolved callees to start DFS from (for a real entry it is `[entry_id]`). Raises `CsdError` on zero candidates without override, multiple `main()`s, or unknown override. `assign_call_order(symtab, sites, entry_id, seeds) -> dict[function_id, int]` — DFS first-visit indices, unreached functions appended in (file, first line) order. Raises `CsdError` on any call-graph cycle reachable from the seeds.

- [ ] **Step 1: Write the failing test**

`tests/test_callorder.py`:

```python
import tempfile
import unittest

from csd import callgraph, callorder, symbols
from csd.schema import CsdError
from tests.helpers import make_package


def analyze(files):
    tmp = tempfile.TemporaryDirectory()
    pkg = make_package(tmp.name, "pkg", files)
    modules = symbols.discover_modules(pkg)
    symtab = symbols.build_symbol_table(modules)
    sites, _ = callgraph.analyze_calls(modules, symtab)
    return tmp, modules, symtab, sites


class EntryAndOrder(unittest.TestCase):
    def test_dfs_first_visit_order_and_unreached(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": """
                def c():
                    return 3

                def b():
                    return c() + c()

                def a():
                    return 1

                def main():
                    x = b()
                    y = a()
                    return x + y

                def orphan():
                    return 0
            """,
        })
        self.addCleanup(tmp.cleanup)
        entry, seeds = callorder.find_entry(symtab, modules, sites)
        self.assertEqual(entry, "pkg.app.main")
        order = callorder.assign_call_order(symtab, sites, entry, seeds)
        # main first, then source-order DFS: b, c (inside b), a; orphan appended
        self.assertEqual(order["pkg.app.main"], 0)
        self.assertEqual(order["pkg.app.b"], 1)
        self.assertEqual(order["pkg.app.c"], 2)
        self.assertEqual(order["pkg.app.a"], 3)
        self.assertEqual(order["pkg.app.orphan"], 4)

    def test_multiple_mains_raise(self):
        tmp, modules, symtab, sites = analyze({
            "one.py": "def main():\n    return 1\n",
            "two.py": "def main():\n    return 2\n",
        })
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(CsdError):
            callorder.find_entry(symtab, modules, sites)

    def test_guard_fallback(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": """
                def run():
                    return 1

                if __name__ == "__main__":
                    run()
            """,
        })
        self.addCleanup(tmp.cleanup)
        entry, seeds = callorder.find_entry(symtab, modules, sites)
        self.assertEqual(entry, "pkg.app.__main__")
        self.assertEqual(seeds, ["pkg.app.run"])
        order = callorder.assign_call_order(symtab, sites, entry, seeds)
        self.assertEqual(order["pkg.app.run"], 0)

    def test_no_entry_raises(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": "def helper():\n    return 1\n",
        })
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(CsdError):
            callorder.find_entry(symtab, modules, sites)

    def test_override_entry(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": "def helper():\n    return 1\n",
        })
        self.addCleanup(tmp.cleanup)
        entry, seeds = callorder.find_entry(
            symtab, modules, sites, override="pkg.app.helper"
        )
        self.assertEqual((entry, seeds), ("pkg.app.helper", ["pkg.app.helper"]))
        with self.assertRaises(CsdError):
            callorder.find_entry(symtab, modules, sites, override="pkg.app.nope")

    def test_cycle_raises(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": """
                def ping():
                    return pong()

                def pong():
                    return ping()

                def main():
                    return ping()
            """,
        })
        self.addCleanup(tmp.cleanup)
        entry, seeds = callorder.find_entry(symtab, modules, sites)
        with self.assertRaises(CsdError):
            callorder.assign_call_order(symtab, sites, entry, seeds)

    def test_self_recursion_raises(self):
        tmp, modules, symtab, sites = analyze({
            "app.py": """
                def main():
                    return main()
            """,
        })
        self.addCleanup(tmp.cleanup)
        entry, seeds = callorder.find_entry(symtab, modules, sites)
        with self.assertRaises(CsdError):
            callorder.assign_call_order(symtab, sites, entry, seeds)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_callorder -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.callorder'`

- [ ] **Step 3: Write minimal implementation**

`csd/callorder.py`:

```python
"""Stage 1c: entry point discovery + DFS first-visit call order.

Cycles (any recursion) are not handled in v1: raise CsdError.
"""
import ast

from .schema import CsdError


def _is_main_guard(stmt):
    return (
        isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.Compare)
        and isinstance(stmt.test.left, ast.Name)
        and stmt.test.left.id == "__name__"
        and len(stmt.test.ops) == 1
        and isinstance(stmt.test.ops[0], ast.Eq)
        and len(stmt.test.comparators) == 1
        and isinstance(stmt.test.comparators[0], ast.Constant)
        and stmt.test.comparators[0].value == "__main__"
    )


def find_entry(symtab, modules, sites, override=None):
    if override:
        if override not in symtab:
            raise CsdError("--entry %r is not a function in the package" % override)
        return override, [override]
    mains = sorted(f.id for f in symtab.values() if f.qualname == "main")
    if len(mains) > 1:
        raise CsdError("multiple main() candidates: %s" % ", ".join(mains))
    if mains:
        return mains[0], [mains[0]]
    for mod in modules:
        for stmt in mod.tree.body:
            if _is_main_guard(stmt):
                span = (stmt.lineno, stmt.end_lineno)
                seeds = [
                    s.callee
                    for s in sites
                    if s.bucket == "resolved"
                    and s.caller == "<module>:" + mod.name
                    and span[0] <= s.line <= span[1]
                ]
                return mod.name + ".__main__", seeds
    raise CsdError(
        "no entry point: define main(), add an __main__ guard, or pass --entry"
    )


def assign_call_order(symtab, sites, entry_id, seeds):
    calls_by_caller = {}
    for s in sites:
        if s.bucket == "resolved" and s.callee:
            calls_by_caller.setdefault(s.caller, []).append(s)
    for lst in calls_by_caller.values():
        lst.sort(key=lambda s: (s.line, s.call.col_offset))

    order = {}
    counter = [0]
    active = set()

    def visit(fid):
        if fid in active:
            raise CsdError(
                "call graph cycle involving %s — recursion is not handled in v1" % fid
            )
        if fid in order:
            return
        order[fid] = counter[0]
        counter[0] += 1
        active.add(fid)
        for site in calls_by_caller.get(fid, []):
            if site.callee in active:
                raise CsdError(
                    "call graph cycle: %s -> %s — recursion is not handled in v1"
                    % (fid, site.callee)
                )
            visit(site.callee)
        active.discard(fid)

    if entry_id in symtab:
        visit(entry_id)
    else:
        for seed in seeds:
            visit(seed)
    unreached = sorted(
        (f for f in symtab.values() if f.id not in order),
        key=lambda f: (f.file, f.lines[0]),
    )
    for f in unreached:
        order[f.id] = counter[0]
        counter[0] += 1
    return order
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_callorder -v`
Expected: `OK`, 7 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd/callorder.py tests/test_callorder.py
git commit -m "feat: stage 1c entry discovery + DFS call order, cycles raise"
```

---

### Task 5: dataflow.py (stage 1d — the core)

**Files:**
- Create: `csd/dataflow.py`, `tests/test_dataflow.py`

**Interfaces:**
- Consumes: `callgraph.CallSite` (matched to AST nodes via `id(site.call)`), `symbols.own_body_nodes` semantics (reimplemented here as a statement flattener), `schema.DataflowEdge`.
- Produces: `Binding(var, site, consumed=False)`; `analyze_dataflow(symtab, sites) -> (edges, consumed_producers, terminal_sites, journal)` where `edges: list[schema.DataflowEdge]`, `consumed_producers: set[function_id]` (every function whose return value is consumed anywhere, including reads that emit no edge), `terminal_sites: list[CallSite]` (resolved call sites whose value was discarded — bare statement or bound-never-read), `journal: dict[function_id, list[Binding]]` (per-scope bindings in bind order; the CLI builds `meta.entry_locals` from the entry's journal).
- Semantics (from the spec): consumption contexts that emit an edge are `("call", callee)` (value passed to a resolved call), `external_call` (read by an external call — consumer is the enclosing function), `return` (returned — consumer is the enclosing function, and the return-sink propagates into composite expressions like `return a + 1`). Reads in any other position (conditions, subscripts, composite args) consume without an edge. `x = f(); x = g(...)` makes f's site terminal if never read in between. Plumbing collapse (`f -> g` instead of `f -> main -> g`) falls out automatically because edges connect the producing callee to the consuming callee.

- [ ] **Step 1: Write the failing test**

`tests/test_dataflow.py`:

```python
import tempfile
import unittest

from csd import callgraph, dataflow, symbols
from tests.helpers import make_package


def run(src):
    tmp = tempfile.TemporaryDirectory()
    pkg = make_package(tmp.name, "pkg", {"m.py": src})
    modules = symbols.discover_modules(pkg)
    symtab = symbols.build_symbol_table(modules)
    sites, _ = callgraph.analyze_calls(modules, symtab)
    edges, consumed, terminal, journal = dataflow.analyze_dataflow(symtab, sites)
    tmp.cleanup()
    return edges, consumed, terminal, journal


def edge_tuples(edges):
    return sorted((e.producer, e.consumer, e.var, e.consumed_by) for e in edges)


BASE = """
    def f():
        return 1

    def g(v):
        return v

    def h(v):
        return v
"""


class Dataflow(unittest.TestCase):
    def test_bound_then_passed_emits_call_edge(self):
        edges, consumed, terminal, _ = run(BASE + """
            def main():
                x = f()
                return g(x)
        """)
        self.assertIn(("pkg.m.f", "pkg.m.g", "x", "call"), edge_tuples(edges))
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual([s.callee for s in terminal], [])

    def test_direct_nesting_emits_anonymous_edge(self):
        edges, _, _, _ = run(BASE + """
            def main():
                return g(f())
        """)
        self.assertIn(("pkg.m.f", "pkg.m.g", "", "call"), edge_tuples(edges))

    def test_discarded_binding_is_terminal(self):
        edges, consumed, terminal, _ = run(BASE + """
            def main():
                x = f()
                return 0
        """)
        self.assertEqual(edges, [])
        self.assertNotIn("pkg.m.f", consumed)
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])

    def test_bare_call_is_terminal(self):
        _, _, terminal, _ = run(BASE + """
            def main():
                f()
                return 0
        """)
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])

    def test_external_read_emits_external_call_edge(self):
        edges, consumed, _, _ = run(BASE + """
            def main():
                x = f()
                print(x)
        """)
        self.assertIn(
            ("pkg.m.f", "pkg.m.main", "x", "external_call"), edge_tuples(edges)
        )
        self.assertIn("pkg.m.f", consumed)

    def test_return_name_emits_return_edge(self):
        edges, _, _, _ = run(BASE + """
            def main():
                x = f()
                return x
        """)
        self.assertIn(("pkg.m.f", "pkg.m.main", "x", "return"), edge_tuples(edges))

    def test_return_composite_propagates(self):
        edges, _, _, _ = run(BASE + """
            def main():
                a = f()
                return a + 1
        """)
        self.assertIn(("pkg.m.f", "pkg.m.main", "a", "return"), edge_tuples(edges))

    def test_conditional_read_consumes_without_edge(self):
        edges, consumed, terminal, _ = run(BASE + """
            def main():
                x = f()
                if x:
                    return 1
                return 0
        """)
        self.assertEqual(edges, [])
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual(terminal, [])

    def test_rebind_makes_first_site_terminal(self):
        edges, consumed, terminal, _ = run(BASE + """
            def main():
                x = f()
                x = g(1)
                return h(x)
        """)
        self.assertEqual([s.callee for s in terminal], ["pkg.m.f"])
        self.assertIn(("pkg.m.g", "pkg.m.h", "x", "call"), edge_tuples(edges))
        self.assertNotIn("pkg.m.f", consumed)

    def test_two_reads_emit_two_edges(self):
        edges, _, _, _ = run(BASE + """
            def main():
                c = f()
                g(c)
                h(c)
        """)
        tuples = edge_tuples(edges)
        self.assertIn(("pkg.m.f", "pkg.m.g", "c", "call"), tuples)
        self.assertIn(("pkg.m.f", "pkg.m.h", "c", "call"), tuples)

    def test_method_read_consumes(self):
        edges, consumed, terminal, _ = run(BASE + """
            def main():
                x = f()
                return x.bit_length()
        """)
        self.assertIn("pkg.m.f", consumed)
        self.assertEqual(terminal, [])

    def test_journal_records_bind_order_and_status(self):
        _, _, _, journal = run(BASE + """
            def main():
                a = f()
                b = g(a)
                dead = h(1)
                print(b)
        """)
        entry = journal["pkg.m.main"]
        self.assertEqual([b.var for b in entry], ["a", "b", "dead"])
        self.assertEqual(
            [b.consumed for b in entry], [True, True, False]
        )
        self.assertEqual(entry[2].site.callee, "pkg.m.h")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_dataflow -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.dataflow'`

- [ ] **Step 3: Write minimal implementation**

`csd/dataflow.py`:

```python
"""Stage 1d: is each produced value consumed, and where does it flow?

Straight-line approximation per the spec: statements are walked in source
order; branch bodies are treated like inline code. Only single-name
assignment targets are tracked; aliasing (y = x) drops tracking.
"""
import ast
from dataclasses import dataclass

from .schema import DataflowEdge

_NESTED_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# sink values used by _Scope.handle_expr:
#   None                  value is read somewhere neutral (condition, composite)
#   "discard"             value is a bare expression statement
#   "bind"                value is about to be bound; do not self-consume
#   ("call", callee_id)   value is a direct argument of a resolved call
#   ("external_call",)    value is a direct argument of an external call
#   ("return",)           value is (part of) a return expression


@dataclass
class Binding:
    var: str
    site: object  # the producing CallSite
    consumed: bool = False


def _flat_statements(fn):
    out = []

    def walk(body):
        for stmt in body:
            if isinstance(stmt, _NESTED_DEFS):
                continue
            out.append(stmt)
            for field in ("body", "orelse", "finalbody"):
                walk(getattr(stmt, field, []) or [])
            for handler in getattr(stmt, "handlers", []) or []:
                walk(handler.body)

    walk(fn.ast_node.body)
    return out


class _Scope:
    def __init__(self, fn, site_by_call, edges, consumed_producers, terminal_sites):
        self.fn = fn
        self.site_by_call = site_by_call
        self.edges = edges
        self.consumed = consumed_producers
        self.terminal = terminal_sites
        self.bindings = {}
        self.journal = []
        self._edge_keys = set()

    def resolved(self, call):
        site = self.site_by_call.get(id(call))
        if site is not None and site.bucket == "resolved":
            return site
        return None

    def emit(self, producer, consumer, var, line, kind):
        key = (producer, consumer, var, kind)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            DataflowEdge(
                producer=producer, consumer=consumer, var=var,
                line=line, consumed_by=kind,
            )
        )

    def consume_name(self, name, sink, line):
        binding = self.bindings.get(name)
        if binding is None:
            return
        binding.consumed = True
        self.consumed.add(binding.site.callee)
        producer = binding.site.callee
        if isinstance(sink, tuple):
            if sink[0] == "call":
                self.emit(producer, sink[1], name, line, "call")
            elif sink[0] == "external_call":
                self.emit(producer, self.fn.id, name, line, "external_call")
            elif sink[0] == "return":
                self.emit(producer, self.fn.id, name, line, "return")

    def handle_expr(self, expr, sink):
        if isinstance(expr, ast.Name):
            if isinstance(expr.ctx, ast.Load):
                self.consume_name(expr.id, sink, expr.lineno)
            return
        if isinstance(expr, ast.Call):
            self._handle_call(expr, sink)
            return
        # composite: reads consume; only the return-sink propagates inward
        inner = sink if sink == ("return",) else None
        for child in ast.iter_child_nodes(expr):
            if isinstance(child, ast.expr):
                self.handle_expr(child, inner)

    def _handle_call(self, call, sink):
        site = self.site_by_call.get(id(call))
        resolved = self.resolved(call)
        if resolved is not None:
            arg_sink = ("call", resolved.callee)
        elif site is not None and site.bucket == "external":
            arg_sink = ("external_call",)
        else:
            arg_sink = None
        for arg in list(call.args) + [kw.value for kw in call.keywords]:
            if isinstance(arg, (ast.Name, ast.Call)):
                self.handle_expr(arg, arg_sink)
            else:
                self.handle_expr(arg, None)
        self.handle_expr(call.func, None)
        if resolved is None or sink == "bind":
            return
        # the resolved call's own value
        if sink == "discard":
            return  # terminal marking happens at the statement level
        self.consumed.add(resolved.callee)
        if isinstance(sink, tuple):
            if sink[0] == "call":
                self.emit(resolved.callee, sink[1], "", call.lineno, "call")
            elif sink[0] == "external_call":
                self.emit(
                    resolved.callee, self.fn.id, "", call.lineno, "external_call"
                )
            elif sink[0] == "return":
                self.emit(resolved.callee, self.fn.id, "", call.lineno, "return")

    def run(self):
        for stmt in _flat_statements(self.fn):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ):
                name = stmt.targets[0].id
                if isinstance(stmt.value, ast.Call):
                    self.handle_expr(stmt.value, "bind")
                    site = self.resolved(stmt.value)
                    if site is not None:
                        binding = Binding(var=name, site=site)
                        self.bindings[name] = binding
                        self.journal.append(binding)
                        continue
                else:
                    self.handle_expr(stmt.value, None)
                self.bindings.pop(name, None)
            elif isinstance(stmt, ast.AugAssign):
                if isinstance(stmt.target, ast.Name):
                    self.consume_name(stmt.target.id, None, stmt.lineno)
                self.handle_expr(stmt.value, None)
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    self.handle_expr(stmt.value, ("return",))
            elif isinstance(stmt, ast.Expr):
                self.handle_expr(stmt.value, "discard")
                if isinstance(stmt.value, ast.Call):
                    site = self.resolved(stmt.value)
                    if site is not None:
                        self.terminal.append(site)
            else:
                for child in ast.iter_child_nodes(stmt):
                    if isinstance(child, ast.expr):
                        self.handle_expr(child, None)
        for binding in self.journal:
            if not binding.consumed:
                self.terminal.append(binding.site)


def analyze_dataflow(symtab, sites):
    site_by_call = {id(s.call): s for s in sites}
    edges = []
    consumed_producers = set()
    terminal_sites = []
    journal = {}
    for fn in sorted(symtab.values(), key=lambda f: (f.file, f.lines[0])):
        scope = _Scope(fn, site_by_call, edges, consumed_producers, terminal_sites)
        scope.run()
        journal[fn.id] = scope.journal
    return edges, consumed_producers, terminal_sites, journal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_dataflow -v`
Expected: `OK`, 12 tests passed.

- [ ] **Step 5: Run the whole suite**

Run: `python -m unittest -v`
Expected: `OK` — schema, symbols, callgraph, callorder, dataflow all green.

- [ ] **Step 6: Commit**

```bash
git add csd/dataflow.py tests/test_dataflow.py
git commit -m "feat: stage 1d dataflow consumption analysis with plumbing collapse"
```

---

### Task 6: iotags.py + deadness.py (stages 1e, 1f)

**Files:**
- Create: `csd/iotags.py`, `csd/deadness.py`, `tests/test_iotags.py`, `tests/test_deadness.py`

**Interfaces:**
- Consumes: `symbols.FunctionInfo` (`.ast_node`), `symbols.own_body_nodes`, `callgraph.dotted_name`, `schema.Node`.
- Produces: `iotags.IO_MARKERS` (the single editable config constant: dict with keys `"names"`, `"dotted"`, `"attrs"`); `iotags.tag_has_io(fn_info) -> bool`; `deadness.mark_dead(nodes: dict[id, schema.Node], consumed_producers: set, resolved_sites: list[CallSite]) -> None` (mutates `Node.is_dead` in place).

- [ ] **Step 1: Write the failing tests**

`tests/test_iotags.py`:

```python
import tempfile
import unittest

from csd import iotags, symbols
from tests.helpers import make_package

SRC = """
    import sys


    def uses_print(x):
        print(x)


    def uses_open(p):
        return open(p)


    def uses_argv():
        return sys.argv[1]


    def uses_read_attr(h):
        return h.read()


    def pure(a):
        return a + 1


    def outer():
        def inner():
            print("hidden")
        return inner
"""


class IoTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"m.py": SRC})
        modules = symbols.discover_modules(pkg)
        self.table = symbols.build_symbol_table(modules)

    def tagged(self, name):
        return iotags.tag_has_io(self.table["pkg.m." + name])

    def test_direct_markers(self):
        self.assertTrue(self.tagged("uses_print"))
        self.assertTrue(self.tagged("uses_open"))
        self.assertTrue(self.tagged("uses_argv"))
        self.assertTrue(self.tagged("uses_read_attr"))

    def test_pure_function_untagged(self):
        self.assertFalse(self.tagged("pure"))

    def test_no_transitive_and_no_nested_leak(self):
        # outer's body only defines inner; the print belongs to inner
        self.assertFalse(self.tagged("outer"))
        self.assertTrue(self.tagged("outer.inner"))


if __name__ == "__main__":
    unittest.main()
```

`tests/test_deadness.py`:

```python
import tempfile
import unittest

from csd import callgraph, callorder, dataflow, deadness, iotags, schema, symbols
from tests.helpers import make_package

SRC = """
    def dead_helper():
        return 42


    def loud_helper():
        print("side effect")
        return 42


    def alive_helper():
        return 1


    def void_helper():
        pass


    def orphan():
        return 9


    def main():
        dead_helper()
        loud_helper()
        void_helper()
        x = alive_helper()
        return x
"""


class Deadness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pkg = make_package(self.tmp.name, "pkg", {"m.py": SRC})
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, _ = callgraph.analyze_calls(modules, symtab)
        resolved = [s for s in sites if s.bucket == "resolved" and s.callee]
        _, consumed, terminal, _ = dataflow.analyze_dataflow(symtab, sites)
        self.nodes = {}
        for f in symtab.values():
            self.nodes[f.id] = schema.Node(
                id=f.id, qualname=f.qualname, module=f.module, file=f.file,
                lines=list(f.lines), params=list(f.params),
                has_io=iotags.tag_has_io(f), returns_value=f.returns_value,
            )
        deadness.mark_dead(self.nodes, consumed, resolved)

    def dead(self, name):
        return self.nodes["pkg.m." + name].is_dead

    def test_discarded_pure_return_is_dead(self):
        self.assertTrue(self.dead("dead_helper"))

    def test_io_saves_from_deadness(self):
        self.assertFalse(self.dead("loud_helper"))

    def test_consumed_value_is_alive(self):
        self.assertFalse(self.dead("alive_helper"))

    def test_no_return_value_is_not_dead(self):
        self.assertFalse(self.dead("void_helper"))

    def test_unreached_is_not_flagged(self):
        self.assertFalse(self.dead("orphan"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_iotags tests.test_deadness -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.iotags'`

- [ ] **Step 3: Write minimal implementations**

`csd/iotags.py`:

```python
"""Stage 1e: direct IO tagging.

IO_MARKERS is the one editable config constant. Direct references in a
function's own body only — no transitive propagation, by design.
"""
import ast

from .callgraph import dotted_name
from .symbols import own_body_nodes

IO_MARKERS = {
    "names": {"open", "print", "input", "socket", "subprocess"},
    "dotted": {"sys.argv", "sys.stdin", "sys.stdout", "sys.stderr", "os.environ"},
    "attrs": {"read", "write"},
}


def tag_has_io(fn_info):
    for node in own_body_nodes(fn_info.ast_node):
        if isinstance(node, ast.Name) and node.id in IO_MARKERS["names"]:
            return True
        if isinstance(node, ast.Attribute):
            if node.attr in IO_MARKERS["attrs"]:
                return True
            dotted = dotted_name(node)
            if dotted in IO_MARKERS["dotted"]:
                return True
    return False
```

`csd/deadness.py`:

```python
"""Stage 1f: one-hop deadness. No transitive chains in v1."""


def mark_dead(nodes, consumed_producers, resolved_sites):
    """A node is dead iff it returns a value, that value is never consumed
    anywhere, it has no direct IO, and it is actually called (unreached
    functions are never flagged, per the spec)."""
    called = {s.callee for s in resolved_sites}
    for node in nodes.values():
        node.is_dead = (
            node.returns_value
            and not node.has_io
            and node.id in called
            and node.id not in consumed_producers
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_iotags tests.test_deadness -v`
Expected: `OK`, 8 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd/iotags.py csd/deadness.py tests/test_iotags.py tests/test_deadness.py
git commit -m "feat: stages 1e/1f IO tagging and one-hop deadness"
```

---

### Task 7: analyze CLI + the specimen package

**Files:**
- Create: `csd/cli.py`, `csd/__main__.py`, `specimen/__init__.py`, `specimen/ingest.py`, `specimen/util.py`, `specimen/categorize.py`, `specimen/summarize.py`, `specimen/report.py`, `specimen/main.py`, `tests/test_cli_analyze.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: `cli.analyze_package(package_path, entry_override=None) -> schema.Graph`; `cli.main(argv=None) -> int` with the `analyze` subcommand (`csd analyze <package_path> -o graph.json [--entry id]`); stdout = exactly three `bucket count` lines in the order resolved, unresolved_dynamic, external. `meta` keys: `tool_version`, `entry_point`, `resolution`, `entry_locals` (list of `{"var", "producer", "status"}` in bind order, status `"consumed"` or `"discarded"`). Call edges with a `<module>:` caller are counted in the buckets but excluded from `graph.call_edges`. The `render` subcommand is added in Task 10.

- [ ] **Step 1: Write the specimen package**

`specimen/__init__.py`:

```python
"""Specimen: a small transaction categorizer with one planted dead call."""
```

`specimen/util.py`:

```python
"""Small pure helpers."""
import hashlib


def clean_text(text):
    return text.strip().replace("\ufeff", "")


def parse_amount(raw):
    return float(raw.strip())


def normalize_merchant(name):
    return " ".join(name.lower().split())


def compute_checksum(records):
    digest = hashlib.sha256()
    for record in records:
        digest.update(repr(sorted(record.items())).encode("utf-8"))
    return digest.hexdigest()
```

`specimen/ingest.py`:

```python
"""Read raw transaction lines from disk and parse them."""
from . import util


def read_lines(path):
    handle = open(path, "r", encoding="utf-8")
    text = handle.read()
    handle.close()
    return text.splitlines()


def parse_line(line):
    cleaned = util.clean_text(line)
    parts = cleaned.split(",")
    amount = util.parse_amount(parts[2])
    return {"date": parts[0], "merchant": parts[1], "amount": amount}


def load_transactions(path):
    lines = read_lines(path)
    transactions = []
    for line in lines:
        if line:
            transactions.append(parse_line(line))
    return transactions
```

`specimen/categorize.py`:

```python
"""Assign a category to each transaction."""
from . import util

CATEGORIES = {"coffee": "food", "grocer": "food", "rent": "housing", "gym": "health"}


def assign_category(merchant):
    normalized = util.normalize_merchant(merchant)
    words = set(normalized.split())
    matches = words & set(CATEGORIES)
    if matches:
        return CATEGORIES[sorted(matches)[0]]
    return "other"


def categorize_all(transactions):
    categorized = []
    for item in transactions:
        category = assign_category(item["merchant"])
        item = dict(item)
        item["category"] = category
        categorized.append(item)
    return categorized
```

`specimen/summarize.py`:

```python
"""Aggregate categorized transactions."""


def total_by_category(transactions):
    categories = {item["category"] for item in transactions}
    return {
        c: sum(t["amount"] for t in transactions if t["category"] == c)
        for c in sorted(categories)
    }


def grand_total(totals):
    return sum(totals.values())


def build_summary(transactions):
    totals = total_by_category(transactions)
    overall = grand_total(totals)
    return {"totals": totals, "overall": overall, "count": len(transactions)}
```

`specimen/report.py`:

```python
"""Render the category summary as text."""


def format_header(title):
    line = "=" * len(title)
    return title + "\n" + line


def format_rows(totals):
    rows = []
    for category in sorted(totals):
        rows.append("%-12s %10.2f" % (category, totals[category]))
    return "\n".join(rows)


def format_footer(overall, count):
    return "%d transactions, %.2f total" % (count, overall)


def render_report(summary):
    header = format_header("Spending by category")
    body = format_rows(summary["totals"])
    footer = format_footer(summary["overall"], summary["count"])
    return header + "\n" + body + "\n" + footer
```

`specimen/main.py`:

```python
"""Entry point: load, categorize, (pointlessly checksum,) summarize, report."""
import sys

from . import categorize, ingest, report, summarize, util


def main():
    path = sys.argv[1]
    transactions = ingest.load_transactions(path)
    categorized = categorize.categorize_all(transactions)
    integrity = util.compute_checksum(categorized)
    summary = summarize.build_summary(categorized)
    text = report.render_report(summary)
    print(text)


if __name__ == "__main__":
    main()
```

Expected analysis facts (asserted in Step 2's test): `compute_checksum` is terminal
and dead; `read_lines` and `main` are the only has_io nodes; `load_transactions`,
`compute_checksum`, `categorize_all`, `format_rows` are the only has_loop nodes
(comprehensions in `summarize.py` deliberately do not count); entry_locals are
`transactions, categorized, integrity, summary, text` with only `integrity` discarded.

- [ ] **Step 2: Write the failing test**

`tests/test_cli_analyze.py`:

```python
import ast
import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from csd import cli, schema

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


class AnalyzePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.nodes = {n.id: n for n in cls.graph.nodes}

    def test_entry_point(self):
        self.assertEqual(self.graph.meta["entry_point"], "specimen.main.main")

    def test_planted_dead_function(self):
        node = self.nodes["specimen.util.compute_checksum"]
        self.assertTrue(node.is_dead)
        self.assertTrue(node.is_terminal)
        for other_id, other in self.nodes.items():
            if other_id != "specimen.util.compute_checksum":
                self.assertFalse(other.is_dead, other_id)

    def test_io_tags(self):
        tagged = sorted(n.id for n in self.graph.nodes if n.has_io)
        self.assertEqual(
            tagged, ["specimen.ingest.read_lines", "specimen.main.main"]
        )

    def test_loop_tags(self):
        looped = sorted(n.id for n in self.graph.nodes if n.has_loop)
        self.assertEqual(
            looped,
            [
                "specimen.categorize.categorize_all",
                "specimen.ingest.load_transactions",
                "specimen.report.format_rows",
                "specimen.util.compute_checksum",
            ],
        )

    def test_entry_locals(self):
        locals_ = self.graph.meta["entry_locals"]
        self.assertEqual(
            [e["var"] for e in locals_],
            ["transactions", "categorized", "integrity", "summary", "text"],
        )
        by_var = {e["var"]: e for e in locals_}
        self.assertEqual(by_var["integrity"]["status"], "discarded")
        for var in ("transactions", "categorized", "summary", "text"):
            self.assertEqual(by_var[var]["status"], "consumed")

    def test_key_dataflow_edges(self):
        tuples = {
            (e.producer, e.consumer, e.var, e.consumed_by)
            for e in self.graph.dataflow_edges
        }
        expected = {
            ("specimen.ingest.load_transactions",
             "specimen.categorize.categorize_all", "transactions", "call"),
            ("specimen.categorize.categorize_all",
             "specimen.util.compute_checksum", "categorized", "call"),
            ("specimen.categorize.categorize_all",
             "specimen.summarize.build_summary", "categorized", "call"),
            ("specimen.summarize.build_summary",
             "specimen.report.render_report", "summary", "call"),
            ("specimen.report.render_report",
             "specimen.main.main", "text", "external_call"),
            ("specimen.summarize.total_by_category",
             "specimen.summarize.grand_total", "totals", "call"),
            ("specimen.report.format_rows",
             "specimen.report.render_report", "body", "return"),
        }
        self.assertTrue(expected.issubset(tuples), expected - tuples)

    def test_counters_invariant(self):
        total = 0
        for root, dirs, files in os.walk(SPECIMEN):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.endswith(".py"):
                    with open(os.path.join(root, fname), encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                    total += sum(
                        isinstance(n, ast.Call) for n in ast.walk(tree)
                    )
        self.assertEqual(sum(self.graph.meta["resolution"].values()), total)

    def test_no_module_level_call_edges(self):
        for edge in self.graph.call_edges:
            self.assertFalse(edge.caller.startswith("<module>:"), edge)

    def test_call_orders_are_unique_and_start_at_entry(self):
        orders = sorted(n.call_order for n in self.graph.nodes)
        self.assertEqual(orders, list(range(len(self.graph.nodes))))
        self.assertEqual(self.nodes["specimen.main.main"].call_order, 0)


class AnalyzeCli(unittest.TestCase):
    def test_stdout_is_exactly_three_counter_lines(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_path = os.path.join(tmp.name, "graph.json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["analyze", SPECIMEN, "-o", out_path])
        self.assertEqual(code, 0)
        lines = buf.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"^resolved \d+$")
        self.assertRegex(lines[1], r"^unresolved_dynamic \d+$")
        self.assertRegex(lines[2], r"^external \d+$")
        with open(out_path, encoding="utf-8") as fh:
            loaded = schema.Graph.from_json(fh.read())
        self.assertEqual(loaded.meta["entry_point"], "specimen.main.main")

    def test_error_exits_nonzero(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["analyze", os.path.join(REPO, "nope"), "-o", "x.json"])
        self.assertEqual(code, 1)
        self.assertIn("csd: error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m unittest tests.test_cli_analyze -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.cli'`

- [ ] **Step 4: Write the implementation**

`csd/cli.py`:

```python
"""CLI and the analyze-side orchestration.

The analyze subcommand's stdout is EXACTLY the three resolution counters.
"""
import argparse
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


def build_parser():
    parser = argparse.ArgumentParser(prog="csd")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="analyze a package into graph.json")
    analyze.add_argument("package_path")
    analyze.add_argument("-o", "--output", required=True)
    analyze.add_argument("--entry", default=None)
    analyze.set_defaults(func=_cmd_analyze)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except schema.CsdError as exc:
        print("csd: error: %s" % exc, file=sys.stderr)
        return 1
```

`csd/__main__.py`:

```python
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest tests.test_cli_analyze -v`
Expected: `OK`, 11 tests passed. If an assertion about specimen facts fails,
the bug is in the analysis stages or the specimen source — debug against the
spec's "Expected verdicts" section, do NOT weaken the test.

- [ ] **Step 6: Run the real CLI once and eyeball it**

Run: `python -m csd analyze specimen -o graph.json`
Expected: exactly three lines like `resolved 30` / `unresolved_dynamic 8` /
`external 12` (numbers are whatever the invariant test confirmed).

- [ ] **Step 7: Run the whole suite, then commit**

Run: `python -m unittest -v`
Expected: `OK`.

```bash
git add csd/cli.py csd/__main__.py specimen tests/test_cli_analyze.py
git commit -m "feat: analyze subcommand + specimen package with planted dead call"
```

---

### Task 8: layout.py (BusLayout behind the LayoutStrategy seam)

**Files:**
- Create: `csd/layout.py`, `tests/test_layout.py`

**Interfaces:**
- Consumes: `schema.Graph` ONLY (the render side must work from a loaded graph.json — never from analysis internals). `cli.analyze_package` is used in tests as a convenient graph source.
- Produces: `LayoutStrategy` (base class; `layout(graph) -> dict[node_id, (side, rank)]`, raises `NotImplementedError`); `BusLayout(LayoutStrategy)` implementing the spec: side is `"bus"` for the entry node, `"above"`/`"below"` for everything else; rank is the longest-path dataflow rank within the node's half (0 = furthest from the bus above, 0 = nearest the bus below). Raises `CsdError` when the entry point is a pseudo-entry (`__main__` guard) with no node, and on any dataflow cycle within a half.

- [ ] **Step 1: Write the failing test**

`tests/test_layout.py`:

```python
import os
import unittest

from csd import cli, layout, schema
from csd.schema import CsdError

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


def node(nid, **kw):
    defaults = dict(
        qualname=nid.rsplit(".", 1)[1], module="pkg.m", file="pkg/m.py",
        lines=[1, 2], params=[], call_order=0, has_io=False, has_loop=False,
        returns_value=True, is_terminal=False, is_dead=False,
    )
    defaults.update(kw)
    return schema.Node(id=nid, **defaults)


class SpecimenLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.placement = layout.BusLayout().layout(cls.graph)

    def side(self, ids):
        return {i: self.placement["specimen." + i][0] for i in ids}

    def test_entry_is_the_bus(self):
        self.assertEqual(self.placement["specimen.main.main"], ("bus", 0))

    def test_output_chain_tail_goes_below(self):
        below = sorted(
            nid for nid, (side, _) in self.placement.items() if side == "below"
        )
        self.assertEqual(below, [
            "specimen.report.format_footer",
            "specimen.report.format_header",
            "specimen.report.format_rows",
            "specimen.report.render_report",
            "specimen.summarize.build_summary",
            "specimen.summarize.grand_total",
            "specimen.summarize.total_by_category",
        ])

    def test_everything_else_goes_above(self):
        above = sorted(
            nid for nid, (side, _) in self.placement.items() if side == "above"
        )
        self.assertEqual(above, [
            "specimen.categorize.assign_category",
            "specimen.categorize.categorize_all",
            "specimen.ingest.load_transactions",
            "specimen.ingest.parse_line",
            "specimen.ingest.read_lines",
            "specimen.util.clean_text",
            "specimen.util.compute_checksum",
            "specimen.util.normalize_merchant",
            "specimen.util.parse_amount",
        ])

    def test_above_ranks_follow_dataflow(self):
        ranks = {
            nid: rank
            for nid, (side, rank) in self.placement.items()
            if side == "above"
        }
        # edges above: load->categorize_all, categorize_all->compute_checksum,
        # parse_amount->parse_line. Everything else is dataflow-isolated and
        # sits at the rank nearest the bus (max rank).
        self.assertEqual(ranks["specimen.ingest.load_transactions"], 0)
        self.assertEqual(ranks["specimen.util.parse_amount"], 0)
        self.assertEqual(ranks["specimen.categorize.categorize_all"], 1)
        self.assertEqual(ranks["specimen.ingest.parse_line"], 1)
        self.assertEqual(ranks["specimen.util.compute_checksum"], 2)
        for isolated in (
            "specimen.ingest.read_lines",
            "specimen.util.clean_text",
            "specimen.util.normalize_merchant",
            "specimen.categorize.assign_category",
        ):
            self.assertEqual(ranks[isolated], 2, isolated)

    def test_below_ranks_follow_dataflow(self):
        ranks = {
            nid: rank
            for nid, (side, rank) in self.placement.items()
            if side == "below"
        }
        self.assertEqual(ranks["specimen.summarize.total_by_category"], 0)
        self.assertEqual(ranks["specimen.report.format_header"], 0)
        self.assertEqual(ranks["specimen.report.format_rows"], 0)
        self.assertEqual(ranks["specimen.report.format_footer"], 0)
        self.assertEqual(ranks["specimen.summarize.grand_total"], 1)
        self.assertEqual(ranks["specimen.summarize.build_summary"], 2)
        self.assertEqual(ranks["specimen.report.render_report"], 3)


class LayoutErrors(unittest.TestCase):
    def test_pseudo_entry_raises(self):
        graph = schema.Graph(
            meta={"entry_point": "pkg.m.__main__", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=[node("pkg.m.run")], call_edges=[], dataflow_edges=[],
        )
        with self.assertRaises(CsdError):
            layout.BusLayout().layout(graph)

    def test_dataflow_cycle_raises(self):
        graph = schema.Graph(
            meta={"entry_point": "pkg.m.main", "entry_locals": [],
                  "resolution": {}, "tool_version": "0.1.0"},
            nodes=[node("pkg.m.main"), node("pkg.m.a"), node("pkg.m.b")],
            call_edges=[
                schema.CallEdge("pkg.m.main", "pkg.m.a", 2),
                schema.CallEdge("pkg.m.main", "pkg.m.b", 3),
            ],
            dataflow_edges=[
                schema.DataflowEdge("pkg.m.a", "pkg.m.b", "x", 2, "call"),
                schema.DataflowEdge("pkg.m.b", "pkg.m.a", "y", 3, "call"),
            ],
        )
        with self.assertRaises(CsdError):
            layout.BusLayout().layout(graph)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_layout -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.layout'`

- [ ] **Step 3: Write the implementation**

`csd/layout.py`:

```python
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
```

Note the isolated-node rule direction: `max_rank` is "nearest the bus" for the
ABOVE half (ranks grow downward toward the bus) but for the BELOW half rank 0 is
nearest the bus. The spec says isolated nodes sit nearest the bus in BOTH halves,
so `_ranks` as written is only correct for the above half. Fix inside `layout()`:
after computing below-half ranks, move isolated below-half nodes to rank 0:

```python
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
```

Use this corrected loop body in the real file (the first listing's loop is
superseded by this one).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_layout -v`
Expected: `OK`, 7 tests passed. If a rank assertion fails, re-derive the half's
edge list by printing `graph.dataflow_edges` — the expected values in the test
were derived by hand from the spec's rules and the specimen's source; fix the
code, not the test, unless the hand derivation itself contradicts the spec.

- [ ] **Step 5: Commit**

```bash
git add csd/layout.py tests/test_layout.py
git commit -m "feat: BusLayout with output-chain split and dataflow ranks"
```

---

### Task 9: render.py (hand-emitted SVG)

**Files:**
- Create: `csd/render.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `schema.Graph`, a placement dict from `layout.BusLayout` (`{node_id: (side, rank)}`).
- Produces: `render_svg(graph, placement) -> str` — a standalone SVG string. Stable emit conventions the tests rely on: every element carries `class="..."` as its FIRST attribute; nodes carry `data-id="<node id>"`; dataflow paths carry `data-var="<var>"`; classes used: `frame`, `bus`, `node`, `node dead`, `io-badge`, `call-edge`, `flow-edge`, `stub` (the synthesized red dead-value stub), `tick` (the ⊥ terminator), `legend-module`, `legend-var`.

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:

```python
import os
import re
import unittest
import xml.etree.ElementTree as ET

from csd import cli, layout, render

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")


class RenderSpecimen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = cli.analyze_package(SPECIMEN)
        cls.placement = layout.BusLayout().layout(cls.graph)
        cls.svg = render.render_svg(cls.graph, cls.placement)

    def test_well_formed_xml(self):
        ET.fromstring(self.svg)
        self.assertTrue(self.svg.startswith("<svg"))

    def test_deterministic(self):
        again = render.render_svg(self.graph, self.placement)
        self.assertEqual(self.svg, again)

    def test_one_shape_per_non_entry_node(self):
        self.assertEqual(self.svg.count('class="node'), 16)

    def test_loop_nodes_are_ellipses(self):
        self.assertEqual(self.svg.count("<ellipse"), 4)

    def test_dead_node_is_red_and_unique(self):
        self.assertEqual(self.svg.count('class="node dead"'), 1)
        match = re.search(
            r'<ellipse class="node dead"[^>]*data-id="([^"]+)"', self.svg
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "specimen.util.compute_checksum")

    def test_dead_stub_and_terminal_tick(self):
        self.assertEqual(self.svg.count('class="stub"'), 1)
        # text -> main() is the one value ending inside the bus
        self.assertEqual(self.svg.count('class="tick"'), 2)  # stub tick + text tick

    def test_io_badges(self):
        self.assertEqual(self.svg.count('class="io-badge"'), 2)

    def test_bus_and_frames(self):
        self.assertEqual(self.svg.count('class="bus"'), 1)
        self.assertIn(">INPUT<", self.svg)
        self.assertIn(">OUTPUT<", self.svg)
        self.assertIn(">main()<", self.svg)

    def test_crossing_value_lands_and_reemerges(self):
        # categorized: one same-half edge (-> compute_checksum) plus a
        # two-segment bus crossing (-> build_summary) = 3 paths
        self.assertEqual(self.svg.count('data-var="categorized"'), 3)

    def test_var_legend_lists_entry_locals_only(self):
        self.assertEqual(self.svg.count('class="legend-var"'), 5)
        for var in ("transactions", "categorized", "integrity", "summary", "text"):
            self.assertIn(">%s<" % var, self.svg)

    def test_module_legend(self):
        for label in ("main.py", "ingest.py", "util.py", "categorize.py",
                      "summarize.py", "report.py"):
            self.assertIn(">%s<" % label, self.svg)

    def test_call_edges_present(self):
        self.assertEqual(
            self.svg.count('class="call-edge"'), len(self.graph.call_edges)
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_render -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'csd.render'`

- [ ] **Step 3: Write the implementation**

`csd/render.py`:

```python
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


def _elbow(x1, y1, x2, y2):
    if x1 == x2:
        return "M %d %d L %d %d" % (x1, y1, x2, y2)
    mid = (y1 + y2) // 2
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

    for e in graph.call_edges:
        if e.caller == entry:
            x = geo.cx(e.callee)
            if placement[e.callee][0] == "above":
                d = "M %d %d L %d %d" % (x, geo.bus_y, x, geo.bottom(e.callee))
            else:
                d = "M %d %d L %d %d" % (
                    x, geo.bus_y + BUS_H, x, geo.top(e.callee)
                )
        else:
            x1, x2 = geo.cx(e.caller), geo.cx(e.callee)
            if geo.cy(e.callee) >= geo.cy(e.caller):
                d = _elbow(x1, geo.bottom(e.caller), x2, geo.top(e.callee))
            else:
                d = _elbow(x1, geo.top(e.caller), x2, geo.bottom(e.callee))
        edges.append(_path("call-edge", d, CALL_COLOR, markers, width=1.2))

    for e in graph.dataflow_edges:
        color = vcolors.get(e.var, ANON_COLOR) if e.var else ANON_COLOR
        if e.consumer == entry:
            x = geo.cx(e.producer)
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
        if pside == cside:
            d = _elbow(
                geo.cx(e.producer), geo.bottom(e.producer),
                geo.cx(e.consumer), geo.top(e.consumer),
            )
            edges.append(_path("flow-edge", d, color, markers, e.var))
        else:
            x1, x2 = geo.cx(e.producer), geo.cx(e.consumer)
            d1 = "M %d %d L %d %d" % (x1, geo.bottom(e.producer), x1, geo.bus_y)
            d2 = "M %d %d L %d %d" % (
                x2, geo.bus_y + BUS_H, x2, geo.top(e.consumer)
            )
            edges.append(_path("flow-edge", d1, color, markers, e.var))
            edges.append(_path("flow-edge", d2, color, markers, e.var))

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
```

Emission-order note: `markers.defs()` must be interpolated AFTER `body` is built
(all `markers.get` calls happen while building `body`), which the final return
statement above does correctly — `body` is a local computed first.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_render -v`
Expected: `OK`, 12 tests passed.

- [ ] **Step 5: Commit**

```bash
git add csd/render.py tests/test_render.py
git commit -m "feat: hand-emitted SVG renderer with bus, stubs, badges, legends"
```

---

### Task 10: render subcommand, end-to-end acceptance, golden file

**Files:**
- Modify: `csd/cli.py` (add render subcommand)
- Create: `tests/test_end_to_end.py`, `tests/golden/specimen_graph.json`

**Interfaces:**
- Consumes: everything.
- Produces: `csd render graph.json -o diagram.svg` subcommand (silent on success); committed golden `tests/golden/specimen_graph.json` locking the full analyze output for the specimen.

- [ ] **Step 1: Write the failing test**

`tests/test_end_to_end.py`:

```python
import contextlib
import io
import os
import tempfile
import unittest

from csd import cli

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECIMEN = os.path.join(REPO, "specimen")
GOLDEN = os.path.join(REPO, "tests", "golden", "specimen_graph.json")


class EndToEnd(unittest.TestCase):
    def test_analyze_then_render(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        graph_path = os.path.join(tmp.name, "graph.json")
        svg_path = os.path.join(tmp.name, "diagram.svg")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                cli.main(["analyze", SPECIMEN, "-o", graph_path]), 0
            )
            self.assertEqual(
                cli.main(["render", graph_path, "-o", svg_path]), 0
            )
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        with open(svg_path, encoding="utf-8") as fh:
            svg = fh.read()
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn('class="node dead"', svg)

    def test_golden_graph_json(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        graph_path = os.path.join(tmp.name, "graph.json")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["analyze", SPECIMEN, "-o", graph_path])
        with open(graph_path, encoding="utf-8") as fh:
            produced = fh.read()
        with open(GOLDEN, encoding="utf-8") as fh:
            golden = fh.read()
        # git on Windows may check the golden out with CRLF; normalize both
        self.assertEqual(
            produced.replace("\r\n", "\n"), golden.replace("\r\n", "\n")
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_end_to_end -v`
Expected: FAIL/ERROR — the `render` subcommand does not exist yet
(`invalid choice: 'render'` exits the parser; the golden file is missing).

- [ ] **Step 3: Add the render subcommand**

In `csd/cli.py`, add after `_cmd_analyze`:

```python
def _cmd_render(args):
    from . import layout, render  # imported here so analyze stays render-free

    with open(args.graph, "r", encoding="utf-8") as fh:
        graph = schema.Graph.from_json(fh.read())
    placement = layout.BusLayout().layout(graph)
    svg = render.render_svg(graph, placement)
    with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
        fh.write("\n")
    return 0
```

And register it inside `build_parser()` before `return parser`:

```python
    rend = sub.add_parser("render", help="render graph.json to an SVG")
    rend.add_argument("graph")
    rend.add_argument("-o", "--output", required=True)
    rend.set_defaults(func=_cmd_render)
```

`argparse` exits with SystemExit(2) on unknown subcommands; that is acceptable
CLI behavior and needs no extra handling.

- [ ] **Step 4: Generate, inspect, and commit the golden file**

```bash
mkdir -p tests/golden
python -m csd analyze specimen -o tests/golden/specimen_graph.json
```

Open `tests/golden/specimen_graph.json` and verify against the spec's
"Expected verdicts": `compute_checksum` has `"is_dead": true`; entry_locals list
the five main locals with integrity discarded; the three resolution counters are
present. Do not commit blindly — this file IS the regression baseline.

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest -v`
Expected: `OK` — every test from every task green.

- [ ] **Step 6: Produce the deliverable SVG and verify the printed counters**

```bash
python -m csd analyze specimen -o graph.json
python -m csd render graph.json -o diagram.svg
```

Expected stdout from analyze: exactly the three counter lines. Open
`diagram.svg` in a browser: INPUT bar top, OUTPUT bar bottom, white main() bus
mid-height, ingest/categorize/util above, summarize/report below,
`compute_checksum` red-outlined with a red ⊥ stub dead-ending on the bus,
IO badges on `read_lines` and the bus, ellipses on the four loop functions,
module legend + variable legend on the right.

- [ ] **Step 7: Commit**

```bash
git add csd/cli.py tests/test_end_to_end.py tests/golden/specimen_graph.json
git commit -m "feat: render subcommand + end-to-end acceptance with golden graph"
```

---

## Plan Self-Review Notes

- **Spec coverage:** 1a→Task 2, 1b→Task 3, 1c→Task 4, 1d→Task 5, 1e/1f→Task 6,
  1g/CLI/specimen→Task 7, layout→Task 8, render→Task 9, deliverable→Task 10.
  `has_loop` (decision #6) lives in Task 2; `entry_locals` (edge-legend feed)
  in Tasks 5/7; the LayoutStrategy seam in Task 8.
- **Known divergences from the hand mockup** (rule-over-sketch, approved):
  dataflow-isolated helpers (read_lines, clean_text, normalize_merchant,
  assign_category) sit at the near-bus rank rather than spread high; format_*
  helpers sit ABOVE render_report per producers-above-consumers.
- **Determinism:** every iteration in the pipeline is over sorted collections
  or insertion-ordered structures derived from sorted walks; `to_json` uses
  sort_keys; the golden test enforces byte stability.

