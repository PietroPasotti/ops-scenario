import pytest
from ops.charm import CharmBase, CharmEvents, StartEvent
from ops.framework import EventSource, EventBase, CommitEvent, PreCommitEvent

from scenario import State
from scenario.utils import capture_events


class FooEvent(EventBase):
    pass


@pytest.fixture
def mycharm():
    class MyCharmEvents(CharmEvents):
        foo = EventSource(FooEvent)

    class MyCharm(CharmBase):
        META = {'name': 'mycharm'}
        on = MyCharmEvents()
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, e):
            if not isinstance(e, FooEvent):
                self.on.foo.emit()

    return MyCharm


def test_capture_all(mycharm):
    with capture_events() as captured:
        State().trigger('start', mycharm, meta=mycharm.META)

    assert len(captured) == 2
    start, foo = captured
    assert isinstance(start, StartEvent)
    assert isinstance(foo, FooEvent)


def test_capture_start(mycharm):
    with capture_events(StartEvent) as captured:
        State().trigger('start', mycharm, meta=mycharm.META)

    assert len(captured) == 1
    assert isinstance(captured[0], StartEvent)


def test_capture_foo(mycharm):
    with capture_events(FooEvent) as captured:
        State().trigger('start', mycharm, meta=mycharm.META)

    assert len(captured) == 1
    assert isinstance(captured[0], FooEvent)


def test_capture_lifecycle(mycharm):
    with capture_events(FooEvent, include_lifecycle_events=True) as captured:
        State().trigger('start', mycharm, meta=mycharm.META)

    assert len(captured) == 3
    foo, precomm, comm = captured
    assert isinstance(foo, FooEvent)
    assert isinstance(comm, CommitEvent)
    assert isinstance(precomm, PreCommitEvent)
