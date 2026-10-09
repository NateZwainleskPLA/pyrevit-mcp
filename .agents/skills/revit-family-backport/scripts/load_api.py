# -*- coding: utf-8 -*-
"""Load one checkout's family API in a running Revit without extension installation."""
import types
import os
import sys


def load_api(repository_path):
    root = os.path.join(repository_path, "revit_mcp")
    if not os.path.isabs(repository_path) or not os.path.isfile(os.path.join(root, "family_backport.py")):
        raise ValueError("Expected an absolute pyrevit-mcp checkout path on the Revit machine")
    namespace = "_pyrevit_family_backport"
    # Reload this isolated namespace so edits in the checkout are not cached.
    # Do not evict or replace the installed revit_mcp package.
    for name in list(sys.modules):
        if name == namespace or name.startswith(namespace + "."):
            del sys.modules[name]
    package = types.ModuleType(namespace)
    package.__path__ = [root]
    sys.modules[namespace] = package
    evidence = __import__(namespace + ".family_backport", fromlist=["inspect_file"])
    rebuild = __import__(namespace + ".family_backport_rebuild", fromlist=["reconstruct_family"])
    evidence.reconstruct_family = rebuild.reconstruct_family
    return evidence
