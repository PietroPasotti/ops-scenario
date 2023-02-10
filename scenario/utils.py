from contextlib import contextmanager
from typing import Type

from ops.framework import EventBase, Framework, CommitEvent, PreCommitEvent


@contextmanager
def capture_events(*types: Type[EventBase], include_lifecycle_events=False):
    """Capture all events of type `*types` (using instance checks).

    If no types are passed, will capture all types.
    """
    def _filter(evt):
        if isinstance(evt, (CommitEvent, PreCommitEvent)):
            if include_lifecycle_events:
                return True
            return False
        if types:
            return isinstance(evt, types)
        return True

    captured = []
    _real_emit = Framework._emit  # type: ignore # noqa # ugly

    def _wrapped_emit(_self, evt):
        if _filter(evt):
            captured.append(evt)
        return _real_emit(_self, evt)

    Framework._emit = _wrapped_emit  # type: ignore # noqa # ugly

    yield captured

    Framework._emit = _real_emit  # type: ignore # noqa # ugly
