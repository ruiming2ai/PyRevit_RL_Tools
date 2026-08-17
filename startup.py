# -*- coding: utf-8 -*-
"""RL Tools extension startup automation."""


try:
    from rltools import coordination_review_passive
    coordination_review_passive.register_passive_detector()
except Exception:
    pass


try:
    from rltools import idling

    # One .NET Idling delegate for RL Tools' deferred work.  A pyRevit hook
    # script would instead be read and recompiled on every Idling event,
    # which Revit raises continuously for the whole session.
    idling.install()
except Exception:
    pass


try:
    from rltools import auto_update

    # Deferred: the first Idling tick runs the guarded update, so git and
    # network work never block the Revit startup thread.
    auto_update.queue_startup_auto_update()
except Exception:
    pass
