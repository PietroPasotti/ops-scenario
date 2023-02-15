import tempfile
from pathlib import Path

import pytest
from ops import pebble
from ops.charm import CharmBase
from ops.framework import Framework
from ops.pebble import ServiceStartup, ServiceStatus

from scenario.state import Container, ExecOutput, Mount, State


@pytest.fixture(scope="function")
def charm_cls():
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_no_containers(charm_cls):
    def callback(self: CharmBase):
        assert not self.unit.containers

    State().trigger(
        charm_type=charm_cls,
        meta={"name": "foo"},
        event="start",
        post_event=callback,
    )


def test_containers_from_meta(charm_cls):
    def callback(self: CharmBase):
        assert self.unit.containers
        assert self.unit.get_container("foo")

    State().trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


@pytest.mark.parametrize("can_connect", (True, False))
def test_connectivity(charm_cls, can_connect):
    def callback(self: CharmBase):
        assert can_connect == self.unit.get_container("foo").can_connect()

    State(containers=[Container(name="foo", can_connect=can_connect)]).trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


def test_fs_push(charm_cls):
    text = "lorem ipsum/n alles amat gloriae foo"
    file = tempfile.NamedTemporaryFile()
    pth = Path(file.name)
    pth.write_text(text)

    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        baz = container.pull("/bar/baz.txt")
        assert baz.read() == text

    State(
        containers=[
            Container(
                name="foo", can_connect=True, mounts={"bar": Mount("/bar/baz.txt", pth)}
            )
        ]
    ).trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


@pytest.mark.parametrize("make_dirs", (True, False))
def test_fs_pull(charm_cls, make_dirs):
    text = "lorem ipsum/n alles amat gloriae foo"

    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        if make_dirs:
            container.push("/foo/bar/baz.txt", text, make_dirs=make_dirs)
            # check that pulling immediately 'works'
            baz = container.pull("/foo/bar/baz.txt")
            assert baz.read() == text
        else:
            with pytest.raises(pebble.PathError):
                container.push("/foo/bar/baz.txt", text, make_dirs=make_dirs)

            # check that nothing was changed
            with pytest.raises(FileNotFoundError):
                container.pull("/foo/bar/baz.txt")

    td = tempfile.TemporaryDirectory()
    state = State(
        containers=[
            Container(
                name="foo", can_connect=True, mounts={"foo": Mount("/foo", td.name)}
            )
        ]
    )

    out = state.trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )

    if make_dirs:
        file = out.get_container("foo").filesystem.open("/foo/bar/baz.txt")
        assert file.read() == text
    else:
        # nothing has changed
        out.juju_log = []
        out.stored_state = state.stored_state  # ignore stored state in delta.
        assert not out.jsonpatch_delta(state)


LS = """
.rw-rw-r--  228 ubuntu ubuntu 18 jan 12:05 -- charmcraft.yaml    
.rw-rw-r--  497 ubuntu ubuntu 18 jan 12:05 -- config.yaml        
.rw-rw-r--  900 ubuntu ubuntu 18 jan 12:05 -- CONTRIBUTING.md    
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:06 -- lib                
.rw-rw-r--  11k ubuntu ubuntu 18 jan 12:05 -- LICENSE            
.rw-rw-r-- 1,6k ubuntu ubuntu 18 jan 12:05 -- metadata.yaml      
.rw-rw-r--  845 ubuntu ubuntu 18 jan 12:05 -- pyproject.toml     
.rw-rw-r--  831 ubuntu ubuntu 18 jan 12:05 -- README.md          
.rw-rw-r--   13 ubuntu ubuntu 18 jan 12:05 -- requirements.txt   
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:05 -- src                
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:05 -- tests              
.rw-rw-r-- 1,9k ubuntu ubuntu 18 jan 12:05 -- tox.ini            
"""
PS = """
    PID TTY          TIME CMD    
 298238 pts/3    00:00:04 zsh    
1992454 pts/3    00:00:00 ps     
"""


@pytest.mark.parametrize(
    "cmd, out",
    (
        ("ls", LS),
        ("ps", PS),
    ),
)
def test_exec(charm_cls, cmd, out):
    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        proc = container.exec([cmd])
        proc.wait()
        assert proc.stdout.read() == "hello pebble"

    State(
        containers=[
            Container(
                name="foo",
                can_connect=True,
                exec_mock={(cmd,): ExecOutput(stdout="hello pebble")},
            )
        ]
    ).trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


def test_pebble_ready(charm_cls):
    def callback(self: CharmBase):
        foo = self.unit.get_container("foo")
        assert foo.can_connect()

    container = Container(name="foo", can_connect=True)

    State(containers=[container]).trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event=container.pebble_ready_event,
        post_event=callback,
    )


def test_pebble_plan(charm_cls):
    def callback(self: CharmBase):
        foo = self.unit.get_container("foo")

        assert foo.get_plan().to_dict() == {
            "services": {"fooserv": {"startup": "enabled"}}
        }
        fooserv = foo.get_services("fooserv")["fooserv"]
        assert fooserv.startup == ServiceStartup.ENABLED
        assert fooserv.current == ServiceStatus.INACTIVE

        foo.add_layer(
            "bar",
            {
                "summary": "bla",
                "description": "deadbeef",
                "services": {"barserv": {"startup": "disabled"}},
            },
        )

        foo.replan()
        assert foo.get_plan().to_dict() == {
            "services": {
                "barserv": {"startup": "disabled"},
                "fooserv": {"startup": "enabled"},
            }
        }

        assert foo.get_service("barserv").current == ServiceStatus.INACTIVE
        foo.start("barserv")
        assert foo.get_service("barserv").current == ServiceStatus.ACTIVE

    container = Container(
        name="foo",
        can_connect=True,
        layers={
            "foo": pebble.Layer(
                {
                    "summary": "bla",
                    "description": "deadbeef",
                    "services": {"fooserv": {"startup": "enabled"}},
                }
            )
        },
    )

    State(containers=[container]).trigger(
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event=container.pebble_ready_event,
        post_event=callback,
    )
