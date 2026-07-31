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
