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

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        elif name == "active_view":
            # Preserve pyRevit's setter behavior without creating a shadowing
            # instance attribute or falling back to the host's active document.
            ScopedRevit.active_view.fset(self, value)
        else:
            raise AttributeError("ScopedRevit does not allow assignment to {0}".format(name))

    @property
    def doc(self):
        return self._document

    @property
    def uidoc(self):
        return self._uidocument

    @property
    def docs(self):
        return () if self._document is None else (self._document,)

    @property
    def active_view(self):
        return None if self._uidocument is None else self._uidocument.ActiveView

    @active_view.setter
    def active_view(self, value):
        if self._uidocument is None:
            raise AttributeError("active_view requires allow_ui_change=True and a supplied eligible UIDocument")
        self._uidocument.ActiveView = value

    @property
    def active_ui_view(self):
        active_view = self.active_view
        if self._uidocument is None or active_view is None:
            return None
        for ui_view in self._uidocument.GetOpenUIViews():
            if ui_view.ViewId == active_view.Id:
                return ui_view
        return None

    def _transaction(self, helper, name, document, args, kwargs):
        document = self._document if document is None else document
        if document is None:
            raise ValueError("A supplied or explicit document is required")
        return getattr(self._module, helper)(name, document, *args, **kwargs)

    def Transaction(self, name=None, doc=None, *args, **kwargs):
        """Bind pyRevit's untracked helper default to the supplied document."""
        return self._transaction("Transaction", name, doc, args, kwargs)

    def TransactionGroup(self, name=None, doc=None, *args, **kwargs):
        return self._transaction("TransactionGroup", name, doc, args, kwargs)

    def __getattr__(self, name):
        if name in ("doc", "uidoc", "docs", "active_view", "active_ui_view",
                    "Transaction", "TransactionGroup"):
            # A property raising AttributeError must not activate a host fallback.
            raise AttributeError("Supplied execution context cannot provide {0}".format(name))
        return getattr(self._module, name)
