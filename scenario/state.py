import copy
import dataclasses
import inspect
import typing
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)
from uuid import uuid4

import yaml
from ops import testing

from scenario.logger import logger as scenario_logger
from scenario.runtime import Runtime

if typing.TYPE_CHECKING:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self
    from ops.pebble import LayerDict
    from ops.testing import CharmType

logger = scenario_logger.getChild("structs")

ATTACH_ALL_STORAGES = "ATTACH_ALL_STORAGES"
CREATE_ALL_RELATIONS = "CREATE_ALL_RELATIONS"
BREAK_ALL_RELATIONS = "BREAK_ALL_RELATIONS"
DETACH_ALL_STORAGES = "DETACH_ALL_STORAGES"
META_EVENTS = {
    "CREATE_ALL_RELATIONS": "-relation-created",
    "BREAK_ALL_RELATIONS": "-relation-broken",
    "DETACH_ALL_STORAGES": "-storage-detaching",
    "ATTACH_ALL_STORAGES": "-storage-attached",
}


@dataclasses.dataclass
class _DCBase:
    def replace(self, *args, **kwargs):
        return dataclasses.replace(self, *args, **kwargs)

    def copy(self) -> "Self":
        return copy.deepcopy(self)


@dataclasses.dataclass
class RelationMeta(_DCBase):
    endpoint: str
    interface: str
    relation_id: int
    remote_app_name: str
    remote_unit_ids: List[int] = dataclasses.field(default_factory=lambda: list((0,)))

    # local limit
    limit: int = 1

    # scale of the remote application; number of units, leader ID?
    # TODO figure out if this is relevant
    scale: int = 1
    leader_id: int = 0


@dataclasses.dataclass
class RelationSpec(_DCBase):
    meta: "RelationMeta"
    local_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    local_unit_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_units_data: Dict[int, Dict[str, str]] = dataclasses.field(
        default_factory=dict
    )

    @property
    def changed_event(self):
        """Sugar to generate a <this relation>-changed event."""
        return Event(
            name=self.meta.endpoint + "-changed", meta=EventMeta(relation=self.meta)
        )

    @property
    def joined_event(self):
        """Sugar to generate a <this relation>-joined event."""
        return Event(
            name=self.meta.endpoint + "-joined", meta=EventMeta(relation=self.meta)
        )

    @property
    def created_event(self):
        """Sugar to generate a <this relation>-created event."""
        return Event(
            name=self.meta.endpoint + "-created", meta=EventMeta(relation=self.meta)
        )

    @property
    def departed_event(self):
        """Sugar to generate a <this relation>-departed event."""
        return Event(
            name=self.meta.endpoint + "-departed", meta=EventMeta(relation=self.meta)
        )

    @property
    def removed_event(self):
        """Sugar to generate a <this relation>-removed event."""
        return Event(
            name=self.meta.endpoint + "-removed", meta=EventMeta(relation=self.meta)
        )


def _random_model_name():
    import random
    import string

    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclasses.dataclass
class Model(_DCBase):
    name: str = _random_model_name()
    uuid: str = str(uuid4())


_SimpleFS = Dict[
    str,  # file/dirname
    Union["_SimpleFS", Path],  # subdir  # local-filesystem path resolving to a file.
]

# for now, proc mock allows you to map one command to one mocked output.
# todo extend: one input -> multiple outputs, at different times


_CHANGE_IDS = 0


@dataclasses.dataclass
class ExecOutput:
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""

    # change ID: used internally to keep track of mocked processes
    _change_id: int = -1

    def _run(self) -> int:
        global _CHANGE_IDS
        _CHANGE_IDS = self._change_id = _CHANGE_IDS + 1
        return _CHANGE_IDS


_ExecMock = Dict[Tuple[str, ...], ExecOutput]


@dataclasses.dataclass
class ContainerSpec(_DCBase):
    name: str
    can_connect: bool = False
    layers: Tuple["LayerDict"] = ()

    # this is how you specify the contents of the filesystem: suppose you want to express that your
    # container has:
    # - /home/foo/bar.py
    # - /bin/bash
    # - /bin/baz
    #
    # this becomes:
    # filesystem = {
    #     'home': {
    #         'foo': Path('/path/to/local/file/containing/bar.py')
    #     },
    #     'bin': {
    #         'bash': Path('/path/to/local/bash'),
    #         'baz': Path('/path/to/local/baz')
    #     }
    # }
    # when the charm runs `pebble.pull`, it will return .open() from one of those paths.
    # when the charm pushes, it will either overwrite one of those paths (careful!) or it will
    # create a tempfile and insert its path in the mock filesystem tree
    # charm-created tempfiles will NOT be automatically deleted -- you have to clean them up yourself!
    filesystem: _SimpleFS = dataclasses.field(default_factory=dict)

    exec_mock: _ExecMock = dataclasses.field(default_factory=dict)


def container(
    name: str,
    can_connect: bool = False,
    layers: Tuple["LayerDict"] = (),
    filesystem: _SimpleFS = None,
    exec_mock: _ExecMock = None,
) -> ContainerSpec:
    """Helper function to instantiate a ContainerSpec."""
    return ContainerSpec(
        name=name,
        can_connect=can_connect,
        layers=layers,
        filesystem=filesystem or {},
        exec_mock=exec_mock or {},
    )


@dataclasses.dataclass
class Address(_DCBase):
    hostname: str
    value: str
    cidr: str


@dataclasses.dataclass
class BindAddress(_DCBase):
    mac_address: str
    interface_name: str
    interfacename: str  # noqa legacy
    addresses: List[Address]

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": self.mac_address,
            "interface-name": self.interface_name,
            "interfacename": self.interfacename,
            "addresses": [dataclasses.asdict(addr) for addr in self.addresses],
        }


@dataclasses.dataclass
class Network(_DCBase):
    bind_addresses: List[BindAddress]
    bind_address: str
    egress_subnets: List[str]
    ingress_addresses: List[str]

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": [ba.hook_tool_output_fmt() for ba in self.bind_addresses],
            "bind-address": self.bind_address,
            "egress-subnets": self.egress_subnets,
            "ingress-addresses": self.ingress_addresses,
        }


@dataclasses.dataclass
class NetworkSpec(_DCBase):
    name: str
    bind_id: int
    network: Network
    is_default: bool = False


@dataclasses.dataclass
class Status(_DCBase):
    app: Tuple[str, str] = ("unknown", "")
    unit: Tuple[str, str] = ("unknown", "")
    app_version: str = ""


@dataclasses.dataclass
class State(_DCBase):
    config: Dict[str, Union[str, int, float, bool]] = None
    relations: Sequence[RelationSpec] = dataclasses.field(default_factory=list)
    networks: Sequence[NetworkSpec] = dataclasses.field(default_factory=list)
    containers: Sequence[ContainerSpec] = dataclasses.field(default_factory=list)
    status: Status = dataclasses.field(default_factory=Status)
    leader: bool = False
    model: Model = Model()
    juju_log: Sequence[Tuple[str, str]] = dataclasses.field(default_factory=list)

    # meta stuff: actually belongs in event data structure.
    juju_version: str = "3.0.0"
    unit_id: str = "0"
    app_name: str = "local"

    # todo: add pebble stuff, unit/app status, etc...
    #  actions?
    #  juju topology

    @property
    def unit_name(self):
        return self.app_name + "/" + self.unit_id

    def with_can_connect(self, container_name: str, can_connect: bool):
        def replacer(container: ContainerSpec):
            if container.name == container_name:
                return container.replace(can_connect=can_connect)
            return container

        ctrs = tuple(map(replacer, self.containers))
        return self.replace(containers=ctrs)

    def with_leadership(self, leader: bool):
        return self.replace(leader=leader)

    def with_unit_status(self, status: str, message: str):
        return self.replace(
            status=dataclasses.replace(self.status, unit=(status, message))
        )

    def get_container(self, name) -> ContainerSpec:
        try:
            return next(filter(lambda c: c.name == name, self.containers))
        except StopIteration as e:
            raise ValueError(f"container: {name}") from e

    def jsonpatch_delta(self, other: "State"):
        try:
            import jsonpatch
        except ModuleNotFoundError:
            logger.error(
                "cannot import jsonpatch: using the .delta() "
                "extension requires jsonpatch to be installed."
                "Fetch it with pip install jsonpatch."
            )
            return NotImplemented
        patch = jsonpatch.make_patch(
            dataclasses.asdict(other), dataclasses.asdict(self)
        ).patch
        return sort_patch(patch)

    def run(
        self,
        event: "Event",
        charm_spec: "CharmSpec",
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> "State":
        runtime = Runtime(charm_spec, juju_version=self.juju_version)
        return runtime.run(
            state=self,
            event=event,
            pre_event=pre_event,
            post_event=post_event,
        )


@dataclasses.dataclass
class CharmSpec(_DCBase):
    """Charm spec."""

    charm_type: Type["CharmType"]
    meta: Optional[Dict[str, Any]]
    actions: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

    @staticmethod
    def from_charm(charm_type: Type["CharmType"]):
        charm_source_path = Path(inspect.getfile(charm_type))
        charm_root = charm_source_path.parent.parent

        metadata_path = charm_root / "metadata.yaml"
        meta = yaml.safe_load(metadata_path.open())

        actions = config = None

        config_path = charm_root / "config.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.open())

        actions_path = charm_root / "actions.yaml"
        if actions_path.exists():
            actions = yaml.safe_load(actions_path.open())

        return CharmSpec(
            charm_type=charm_type, meta=meta, actions=actions, config=config
        )


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)


@dataclasses.dataclass
class EventMeta(_DCBase):
    # if this is a relation event, the metadata of the relation
    relation: Optional[RelationMeta] = None
    # todo add other meta for
    #  - secret events
    #  - pebble?
    #  - action?


@dataclasses.dataclass
class Event(_DCBase):
    name: str
    args: Tuple[Any] = ()
    kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)
    meta: EventMeta = None

    @property
    def is_meta(self):
        """Is this a meta event?"""
        return self.name in META_EVENTS


@dataclasses.dataclass
class Inject(_DCBase):
    """Base class for injectors: special placeholders used to tell harness_ctx
    to inject instances that can't be retrieved in advance in event args or kwargs.
    """

    pass


@dataclasses.dataclass
class InjectRelation(Inject):
    relation_name: str
    relation_id: Optional[int] = None


def relation(
    endpoint: str,
    interface: str,
    remote_app_name: str = "remote",
    relation_id: int = 0,
    remote_unit_ids: List[
        int
    ] = None,  # defaults to (0,) if remote_units_data is not provided
    # mapping from unit ID to databag contents
    local_unit_data: Dict[str, str] = None,
    local_app_data: Dict[str, str] = None,
    remote_app_data: Dict[str, str] = None,
    remote_units_data: Dict[int, Dict[str, str]] = None,
):
    """Helper function to construct a RelationMeta object with some sensible defaults."""
    if remote_unit_ids and remote_units_data:
        if not set(remote_unit_ids) == set(remote_units_data):
            raise ValueError(
                f"{remote_unit_ids} should include any and all IDs from {remote_units_data}"
            )
    elif remote_unit_ids:
        remote_units_data = {x: {} for x in remote_unit_ids}
    elif remote_units_data:
        remote_unit_ids = [x for x in remote_units_data]
    else:
        remote_unit_ids = [0]
        remote_units_data = {0: {}}

    metadata = RelationMeta(
        endpoint=endpoint,
        interface=interface,
        remote_app_name=remote_app_name,
        remote_unit_ids=remote_unit_ids,
        relation_id=relation_id,
    )
    return RelationSpec(
        meta=metadata,
        local_unit_data=local_unit_data or {},
        local_app_data=local_app_data or {},
        remote_app_data=remote_app_data or {},
        remote_units_data=remote_units_data,
    )


def network(
    private_address: str = "1.1.1.1",
    mac_address: str = "",
    hostname: str = "",
    cidr: str = "",
    interface_name: str = "",
    egress_subnets=("1.1.1.2/32",),
    ingress_addresses=("1.1.1.2",),
) -> Network:
    """Construct a network object."""
    return Network(
        bind_addresses=[
            BindAddress(
                mac_address=mac_address,
                interface_name=interface_name,
                interfacename=interface_name,
                addresses=[
                    Address(hostname=hostname, value=private_address, cidr=cidr)
                ],
            )
        ],
        bind_address=private_address,
        egress_subnets=list(egress_subnets),
        ingress_addresses=list(ingress_addresses),
    )


def _derive_args(event_name: str):
    args = []
    terms = {
        "-relation-changed",
        "-relation-broken",
        "-relation-joined",
        "-relation-departed",
        "-relation-created",
    }

    for term in terms:
        # fixme: we can't disambiguate between relation IDs.
        if event_name.endswith(term):
            args.append(InjectRelation(relation_name=event_name[: -len(term)]))

    return tuple(args)


def event(
    name: str, append_args: Tuple[Any] = (), meta: EventMeta = None, **kwargs
) -> Event:
    """This routine will attempt to generate event args for you, based on the event name."""
    return Event(
        name=name, args=_derive_args(name) + append_args, kwargs=kwargs, meta=meta
    )