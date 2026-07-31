"""Stage 1c: entry point discovery + DFS first-visit call order.

Recursion is fine here: a call back into a function already visited is not
a new position in the run, so first-visit order is well defined either way.
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
                guard_sites = sorted(
                    (
                        s
                        for s in sites
                        if s.bucket == "resolved"
                        and s.caller == "<module>:" + mod.name
                        and span[0] <= s.line <= span[1]
                    ),
                    key=lambda s: (s.line, s.call.col_offset),
                )
                return mod.name + ".__main__", [s.callee for s in guard_sites]
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

    def visit(fid):
        # first visit wins; a call back into something already seen is
        # recursion, not a new position in the run
        if fid in order:
            return
        order[fid] = counter[0]
        counter[0] += 1
        for site in calls_by_caller.get(fid, []):
            visit(site.callee)

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
