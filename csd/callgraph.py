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
            base = _resolve_from(mod.name, node, mod.file.endswith("__init__.py"))
            for alias in node.names:
                imports[alias.asname or alias.name] = base + "." + alias.name
    return imports


def _resolve_from(module_name, node, is_package):
    if node.level == 0:
        return node.module
    parts = module_name.split(".")
    # a package's __init__ IS its package: level 1 strips nothing there
    strip = node.level - 1 if is_package else node.level
    base = parts[: len(parts) - strip] if strip else parts[:]
    if node.module:
        base.append(node.module)
    if not base:
        raise CsdError(
            "relative import escapes the package at %s line %d"
            % (module_name, node.lineno)
        )
    return ".".join(base)


def _enclosing_scopes(mod_name, caller_qual, symtab):
    """Function scopes a bare name can resolve against, innermost first.

    A class body is NOT one of them: `second()` inside a method is a
    NameError at runtime, not a call to a sibling method. Class frames are
    exactly the qualname prefixes that are not themselves functions.
    """
    if not caller_qual:
        return []
    parts = caller_qual.split(".")
    scopes = []
    for depth in range(len(parts), 0, -1):
        prefix = "%s.%s" % (mod_name, ".".join(parts[:depth]))
        if prefix in symtab:
            scopes.append(prefix)
    return scopes


def _classify(call, caller_qual, mod_name, imports, symtab, pkg):
    func = call.func
    caller_class = (
        caller_qual.rsplit(".", 1)[0]
        if caller_qual and "." in caller_qual else None
    )
    if isinstance(func, ast.Name):
        # local and enclosing function scopes shadow module-level names
        for scope in _enclosing_scopes(mod_name, caller_qual, symtab):
            nested = "%s.%s" % (scope, func.id)
            if nested in symtab:
                return "resolved", nested
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
                caller, caller_qual = f.id, f.qualname
            else:
                caller, caller_qual = "<module>:" + mod.name, None
            bucket, callee = _classify(
                call, caller_qual, mod.name, imports, symtab, pkg
            )
            counters[bucket] += 1
            sites.append(CallSite(caller, callee, call.lineno, bucket, call))
    return sites, counters
