# -*- coding: utf-8 -*-
"""Process queued RL Tools file-open startup work."""

from rltools.messages import has_pending_startup_jobs
from rltools.messages import process_startup_jobs


try:
    if has_pending_startup_jobs():
        process_startup_jobs()
except Exception:
    # Never hard-fail Revit idling because of startup automation.
    pass
