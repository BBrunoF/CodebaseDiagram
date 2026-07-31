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
