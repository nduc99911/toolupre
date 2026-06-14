"""
Shared memory for progress tracking across services.
"""
video_progress: dict[str, float] = {}
video_logs: dict[str, list[str]] = {}
active_processes: dict[str, any] = {}
