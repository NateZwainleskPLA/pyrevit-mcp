# -*- coding: utf-8 -*-
from listener_probe import current

__persistentengine__ = True
print(current().event.Raise())
