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

    if not auto_update.should_skip_startup(auto_update.get_startup_guard_state()):
        auto_update.mark_startup_attempted()
        auto_update.run_startup_auto_update()
except Exception:
    pass
