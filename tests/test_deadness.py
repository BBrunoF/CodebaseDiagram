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


class ModuleLevelConsumption(unittest.TestCase):
    def test_module_called_function_is_never_flagged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pkg = make_package(tmp.name, "pkg", {"app.py": """
            def compute():
                return 42

            if __name__ == "__main__":
                result = compute()
                print(result)
        """})
        modules = symbols.discover_modules(pkg)
        symtab = symbols.build_symbol_table(modules)
        sites, _ = callgraph.analyze_calls(modules, symtab)
        resolved = [s for s in sites if s.bucket == "resolved" and s.callee]
        _, consumed, _, _ = dataflow.analyze_dataflow(symtab, sites)
        nodes = {}
        for f in symtab.values():
            nodes[f.id] = schema.Node(
                id=f.id, qualname=f.qualname, module=f.module, file=f.file,
                lines=list(f.lines), params=list(f.params),
                has_io=iotags.tag_has_io(f), returns_value=f.returns_value,
            )
        deadness.mark_dead(nodes, consumed, resolved)
        self.assertFalse(nodes["pkg.app.compute"].is_dead)


if __name__ == "__main__":
    unittest.main()
