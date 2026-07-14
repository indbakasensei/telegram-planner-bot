"""
core.storage -- Storage Facade (v14.1C), minimum infrastructure required
for the Offline Engine. See storage.py's module docstring for the Phase 0
design review (Facade chosen over a Repository Layer) and hard rules
(no SQL, no business logic, pure delegation to database.py).

Not yet consumed anywhere -- no Offline Engine exists to call it. See
DEBUGGING.md.
"""
from core.storage.storage import GoalStorage, HabitStorage, ProjectStorage, Storage, TaskStorage

__all__ = ["Storage", "TaskStorage", "HabitStorage", "GoalStorage", "ProjectStorage"]
