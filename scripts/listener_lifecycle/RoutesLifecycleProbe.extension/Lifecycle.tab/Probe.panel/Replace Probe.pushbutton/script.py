# -*- coding: utf-8 -*-
from listener_probe import current, initialize

__persistentengine__ = True
initialize(__revit__, current().path)
