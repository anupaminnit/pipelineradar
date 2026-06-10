"""APScheduler loop for autonomous scheduled execution.

Runs the pipeline graph on a configurable cron schedule. Emits a structured
log line at the start and end of every run including run_id, duration, and
item counts.

Phase 4: implement start_scheduler(settings: Settings) -> None.
"""

from __future__ import annotations

# Phase 4: implement start_scheduler
