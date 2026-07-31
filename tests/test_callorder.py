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
