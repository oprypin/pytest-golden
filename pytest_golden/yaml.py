from typing import Any, Callable, Type

import ruamel.yaml

UserType = Any
YamlType = Any

_safe = ruamel.yaml.YAML(typ="safe", pure=True)
_rt = ruamel.yaml.YAML(typ="rt", pure=True)


def register_class(cls: Type) -> None:
    _safe.register_class(cls)
    _rt.register_class(cls)


def add_representer(
    data_type: Type, representer: Callable[[ruamel.yaml.BaseRepresenter, UserType], YamlType]
) -> None:
    _safe.representer.add_representer(data_type, representer)
    _rt.representer.add_representer(data_type, representer)


def add_multi_representer(
    base_data_type: Type,
    multi_representer: Callable[[ruamel.yaml.BaseRepresenter, UserType], YamlType],
) -> None:
    _safe.representer.add_multi_representer(base_data_type, multi_representer)
    _rt.representer.add_multi_representer(base_data_type, multi_representer)


def add_constructor(
    tag: str, constructor: Callable[[ruamel.yaml.BaseConstructor, YamlType], UserType]
) -> None:
    _safe.constructor.add_constructor(tag, constructor)
    _rt.constructor.add_constructor(tag, constructor)


def add_multi_constructor(
    tag_prefix: str,
    multi_constructor: Callable[[ruamel.yaml.BaseConstructor, str, YamlType], UserType],
) -> None:
    _safe.constructor.add_multi_constructor(tag_prefix, multi_constructor)
    _rt.constructor.add_multi_constructor(tag_prefix, multi_constructor)


def _prepare_for_output(d: dict) -> None:
    ruamel.yaml.scalarstring.walk_tree(d)
