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
