# -*- coding: utf-8 -*-
import os
from listener_probe import initialize

__persistentengine__ = True
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
initialize(__revit__, os.path.join(root, 'lifecycle-evidence.json'))
