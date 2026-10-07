# -*- coding: utf-8 -*-
from listener_probe import current

__persistentengine__ = True
probe = current()
probe.capture()
print(probe.inspect())
