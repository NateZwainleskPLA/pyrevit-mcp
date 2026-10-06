# -*- coding: UTF-8 -*-
"""Bind common pyRevit context properties to the validated execution document."""


class ScopedRevit(object):
    """Context facade, not a security sandbox for arbitrary IronPython scripts.

    Other pyRevit helpers delegate unchanged and may have their own implicit
    host context. Scripts must pass doc explicitly to such helpers. Routing can
    supply a stricter facade through execute_payload's revit_context argument.
    """
    def __init__(self, module, document, uidocument):
        self._module = module
        self._document = document
        self._uidocument = uidocument

    @property
    def doc(self):
        return self._document

    @property
    def uidoc(self):
        return self._uidocument

    def __getattr__(self, name):
        return getattr(self._module, name)
