import pytest
import yaml

pytest.register_assert_rewrite("pytest_golden.plugin")


class MultilineString(str):
    pass


yaml.add_representer(
    MultilineString,
    lambda dumper, data: dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|"),
)
