"""Stage 1a: the symbol table.

Walks every .py file under the package path and records every function
and method, including nested ones.
"""
import ast
import fnmatch
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


def _excluded(rel_path, patterns):
    """Match a package-relative path against a glob, by full path or by
    basename, so `vendor`, `vendor/*` and `*_pb2.py` all read naturally."""
    base = rel_path.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(base, pat)
        for pat in patterns
    )


def discover_modules(package_path, excludes=(), skipped=None):
    package_path = os.path.abspath(package_path)
    if not os.path.isdir(package_path):
        raise CsdError("package path is not a directory: %s" % package_path)
    parent = os.path.dirname(package_path)
    modules = []
    for root, dirs, files in os.walk(package_path):
        dirs.sort()
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if excludes:
            kept = []
            for d in dirs:
                inner = os.path.relpath(
                    os.path.join(root, d), package_path
                ).replace(os.sep, "/")
                if _excluded(inner, excludes):
                    if skipped is not None:
                        skipped.append(inner + "/")
                else:
                    kept.append(d)
            dirs[:] = kept
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            full = os.path.join(root, fname)
            inner = os.path.relpath(full, package_path).replace(os.sep, "/")
            if excludes and _excluded(inner, excludes):
                if skipped is not None:
                    skipped.append(inner)
                continue
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
    # a generator hands a value back to its caller without ever `return`ing
    # one, so yield counts too
    return any(
        (isinstance(n, ast.Return) and n.value is not None)
        or isinstance(n, (ast.Yield, ast.YieldFrom))
        for n in own_body_nodes(fn)
    )


def _has_loop(fn):
    return any(
        isinstance(n, (ast.For, ast.AsyncFor, ast.While))
        for n in own_body_nodes(fn)
    )


def _is_overload_stub(fn):
    """@overload / @typing.overload declares a signature, not a function."""
    for dec in fn.decorator_list:
        name = dec.attr if isinstance(dec, ast.Attribute) else getattr(dec, "id", None)
        if name == "overload":
            return True
    return False


def _functions_with_qualnames(tree):
    found = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_overload_stub(child):
                    continue
                qual = prefix + child.name
                found.append((child, qual))
                visit(child, qual + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def build_symbol_table(modules, redefined=None):
    """Build the symbol table.

    A name defined twice in one module — platform branches, an import
    fallback — keeps its FIRST definition, which is the default
    configuration. Every id that was redefined is appended to `redefined`
    so the caller can report it rather than silently dropping code.
    """
    table = {}
    for mod in modules:
        for fn, qual in _functions_with_qualnames(mod.tree):
            fid = "%s.%s" % (mod.name, qual)
            if fid in table:
                if redefined is not None and fid not in redefined:
                    redefined.append(fid)
                continue
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
