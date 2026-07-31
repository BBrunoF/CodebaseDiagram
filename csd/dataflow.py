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
            for case in getattr(stmt, "cases", []) or []:
                walk(case.body)

    walk(fn.ast_node.body)
    return out


class _Scope:
    def __init__(self, fn, site_by_call, edges, consumed_producers, terminal_sites, edge_keys):
        self.fn = fn
        self.site_by_call = site_by_call
        self.edges = edges
        self.consumed = consumed_producers
        self.terminal = terminal_sites
        self.bindings = {}
        self.journal = []
        self._edge_keys = edge_keys

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

    def _child_exprs(self, node):
        """Direct child expressions, looking through non-expr containers
        (comprehension clauses, with-items) that would otherwise hide
        the calls inside them."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                yield child
            elif isinstance(child, (ast.comprehension, ast.withitem)):
                for sub in self._child_exprs(child):
                    yield sub

    def _bind_name(self, name, value):
        if isinstance(value, ast.Call):
            self.handle_expr(value, "bind")
            site = self.resolved(value)
            if site is not None:
                binding = Binding(var=name, site=site)
                self.bindings[name] = binding
                self.journal.append(binding)
                return
        else:
            self.handle_expr(value, None)
        self.bindings.pop(name, None)

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
        for child in self._child_exprs(expr):
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
                self._bind_name(stmt.targets[0].id, stmt.value)
            elif (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.value is not None
            ):
                self._bind_name(stmt.target.id, stmt.value)
            elif isinstance(stmt, ast.AugAssign):
                if isinstance(stmt.target, ast.Name):
                    self.consume_name(stmt.target.id, None, stmt.lineno)
                    # the name now holds a transformed value; drop tracking
                    self.bindings.pop(stmt.target.id, None)
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
                for child in self._child_exprs(stmt):
                    self.handle_expr(child, None)
        for binding in self.journal:
            if not binding.consumed:
                self.terminal.append(binding.site)


def analyze_dataflow(symtab, sites):
    site_by_call = {id(s.call): s for s in sites}
    edges = []
    consumed_producers = set()
    terminal_sites = []
    edge_keys = set()
    journal = {}
    for fn in sorted(symtab.values(), key=lambda f: (f.file, f.lines[0])):
        scope = _Scope(fn, site_by_call, edges, consumed_producers, terminal_sites, edge_keys)
        scope.run()
        journal[fn.id] = scope.journal
    return edges, consumed_producers, terminal_sites, journal
