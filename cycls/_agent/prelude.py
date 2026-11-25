"""Where a turn's time goes before its first model call. A run's clock starts as the request arrives, and 1–10 s
passed before the model was first called (super-dev logs, 2026-11-25): each step marks when it ends, and the steps
are logged once, as `prelude`, just before that call."""
import contextvars, time

_MARKS = contextvars.ContextVar("prelude_marks", default=None)


def start():
    """The request arrived: a new list of marks, shared with the run's task (it copies this context)."""
    _MARKS.set([("arrived", time.monotonic())])


def mark(step):
    """`step` has just ended."""
    marks = _MARKS.get()
    if marks is not None:
        marks.append((step, time.monotonic()))


def take():
    """({step: ms}, total ms) since the request arrived — once per run, then None."""
    marks = _MARKS.get()
    if not marks or len(marks) < 2:
        return None
    steps = {}
    for (_, before), (step, at) in zip(marks, marks[1:]):
        steps[step] = steps.get(step, 0) + int((at - before) * 1000)
    total = int((marks[-1][1] - marks[0][1]) * 1000)
    marks.clear()
    return steps, total
