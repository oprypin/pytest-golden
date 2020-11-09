import collections
import contextlib
import dataclasses
import inspect
import logging
import pathlib
import warnings
from typing import Any, Callable, Collection, Dict, List, Optional, Sequence, Type, TypeVar, Union

import atomicwrites
import pytest
import yaml

from . import MultilineString

T = TypeVar("T")


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="reset golden master benchmarks",
    )


@pytest.fixture
def golden(request):
    try:
        args = request.param
    except AttributeError:
        args = (None, request.function)
    fixt = GoldenTestFixture(
        *args,
        update_goldens=request.config.getoption("--update-goldens"),
        assertions_enabled=request.config.getini("enable_assertion_pass_hook"),
    )
    yield fixt
    fixt.teardown(request.node)


FIXTURE_NAME = golden.__name__
MARKER_NAME = "golden_test"


def pytest_configure(config):
    if not config.getini("enable_assertion_pass_hook"):
        warnings.warn(
            "Add 'enable_assertion_pass_hook=true' to pytest.ini for safer usage of pytest-golden.",
            GoldenTestUsageWarning,
        )
    config.addinivalue_line("markers", MARKER_NAME + "(*file_patterns): TODO")


def _golden_test_marker(*file_patterns: str):
    return file_patterns


class UsageError(Exception):
    pass


class GoldenTestUsageWarning(Warning):
    pass


@dataclasses.dataclass
class GoldenTestFixture:
    path: Optional[pathlib.Path]
    func: Callable
    update_goldens: bool
    assertions_enabled: bool
    name = FIXTURE_NAME

    def __post_init__(self):
        if self.path is None:
            return

        with self.path.open(encoding="utf-8") as f:
            inputs = yaml.safe_load(f)
        if inputs is None:
            inputs = {}
        elif not isinstance(inputs, dict):
            raise UsageError(f"The YAML file '{path}' must contain a dict at the top level.")

        self.inputs: Dict[str, Any] = inputs
        if self.update_goldens:
            self.out = GoldenOutputProxy(self)
            self._records: List[Union["_ComparisonRecord", "_AssertionRecord"]] = []
        else:
            self.out = self.inputs

    def __getitem__(self, key: str) -> Any:
        return self.inputs[key]

    def get(self, key: str) -> Optional[Any]:
        return self.inputs.get(key)

    def teardown(self, item):
        if not self.update_goldens:
            return

        actual: Dict[str, Union[_AbsentValue, Any]] = {}
        approved_lines: List[int] = []
        to_warn: List[Tuple[str, _ComparisonRecord]] = []
        warn = lambda *args: to_warn.append(args)

        for record in reversed(self._records):
            if isinstance(record, _AssertionRecord):
                approved_lines.append(record.lineno)
            elif isinstance(record, _ComparisonRecord):
                comparison = record.comparison
                if record.location.lineno in approved_lines:
                    comparison.approve()
                if self.assertions_enabled and not comparison.approved:
                    warn(
                        f"Comparison to a golden output {record.key!r} outside of an assert is ignored:"
                        f"\n{comparison}",
                        record,
                    )
                    continue
                value = record.other
                if comparison.optional and value is None:
                    value = _AbsentValue()
                if comparison.key in actual and actual[comparison.key] != value:
                    warn(
                        f"Comparison to golden output {comparison.key!r} has gotten conflicting values: "
                        f"{record.other!r} vs {actual[comparison.key]!r}",
                        record,
                    )
                    continue
                actual[record.key] = value

        for msg, record in reversed(to_warn):
            warnings.warn_explicit(
                msg, GoldenTestUsageWarning, record.location.filename, record.location.lineno
            )

        outputs = collections.ChainMap(actual, self.inputs)
        outputs = {
            k: MultilineString(v) if isinstance(v, str) else v
            for k, v in outputs.items()
            if not isinstance(v, _AbsentValue)
        }
        with atomicwrites.atomic_write(self.path, mode="w", encoding="utf-8", overwrite=True) as f:
            yaml.dump(outputs, f, sort_keys=False, width=1 << 32)

    @contextlib.contextmanager
    def may_raise(self, cls: Type[Exception], *, key: str = "exception"):
        try:
            yield
        except cls as e:
            assert self.out.get(key) == {type(e).__name__: MultilineString(e)}
        else:
            assert self.out.get(key) == None

    @contextlib.contextmanager
    def capture_logs(
        self,
        loggers: Union[str, Sequence[str]],
        level: int = logging.INFO,
        attributes: Sequence[str] = ("levelname", "getMessage"),
        *,
        key: str = "logs",
    ):
        import testfixtures

        with testfixtures.LogCapture(loggers, attributes=attributes, level=level) as capture:
            yield
        logs = [":".join(log) for log in capture.actual()] or None
        assert self.out.get(key) == logs


@dataclasses.dataclass
class GoldenOutputProxy:
    fixt: GoldenTestFixture

    def __getitem__(self, key: str) -> "GoldenOutput":
        return GoldenOutput(self.fixt, key)

    def get(self, key: str) -> "GoldenOutput":
        return GoldenOutput(self.fixt, key, optional=True)


@dataclasses.dataclass
class GoldenOutput:
    fixt: GoldenTestFixture
    key: str
    optional: bool = False

    @property
    def value(self):
        return self.fixt[self.key]

    def __eq__(self, other) -> "GoldenComparison":
        if isinstance(other, GoldenOutput):
            raise TypeError("Can't compare two golden output placeholders")
        return GoldenComparison(self.fixt, self.key, other, self.optional)

    def __ne__(self, other) -> "GoldenComparison":
        if isinstance(other, GoldenOutput):
            raise TypeError("Can't compare two golden output placeholders")
        warnings.warn(
            "Only '==' comparison should be used on a golden output",
            GoldenTestUsageWarning,
            stacklevel=2,
        )
        return GoldenComparison(self.fixt, self.key, other, self.optional, eq=False)

    def __str__(self) -> str:
        return f"{self.fixt.name}.out[{self.key!r}]"


@dataclasses.dataclass
class GoldenComparison:
    fixt: GoldenTestFixture
    key: str
    other: Any
    optional: bool
    eq: bool = True
    approved: bool = False

    def __bool__(self) -> bool:
        stack = inspect.stack()
        approved = [
            inspect.unwrap(f).__code__
            for f in (self.fixt.func, GoldenTestFixture.may_raise, GoldenTestFixture.capture_logs)
        ]
        for info in stack:
            if info.frame.f_code in approved:
                self.fixt._records.append(_ComparisonRecord(self, inspect.getframeinfo(info.frame)))
                break
        return self.eq

    def __str__(self) -> str:
        op = "==" if self.eq else "!="
        return f"{self.other!r} {op} {self.fixt.name}.out[{self.key!r}]"

    def approve(self: T) -> T:
        if isinstance(self, GoldenComparison):
            self.approved = True
        return self


@dataclasses.dataclass
class _ComparisonRecord:
    comparison: "GoldenComparison"
    location: inspect.FrameInfo

    @property
    def key(self) -> str:
        return self.comparison.key

    @property
    def other(self):
        return self.comparison.other


@dataclasses.dataclass
class _AssertionRecord:
    lineno: int


@dataclasses.dataclass
class _AbsentValue:
    def __repr__(self):
        return "<absent>"


def pytest_generate_tests(metafunc):
    item = metafunc.definition
    marker = item.get_closest_marker(MARKER_NAME)
    if not marker:
        return
    patterns = _golden_test_marker(*marker.args, **marker.kwargs)

    def warn(msg):
        warnings.warn_explicit(
            f"{msg}: {metafunc.function}",
            GoldenTestUsageWarning,
            f_code.co_filename,
            f_code.co_firstlineno,
        )

    if FIXTURE_NAME not in metafunc.fixturenames:
        f_code = metafunc.function.__code__
        warn(f"Useless '{MARKER_NAME}' marker on a test without a '{FIXTURE_NAME}' fixture")
        return

    directory = pathlib.Path(metafunc.module.__file__).parent
    paths: Collection[pathlib.Path] = dict.fromkeys(
        path for pattern in patterns for path in directory.glob(pattern)
    )
    if not paths:
        warn(f"The patterns {patterns!r} didn't match anything")
        return

    # `::test_foo[foo/*.yaml]` -> `::test_foo[*.yaml]`
    rel_paths = [path.relative_to(directory) for path in paths]
    skip_parts = None
    item.originalname
    if all("test_" + path.parts[0] == item.originalname for path in rel_paths):
        skip_parts = 1
    ids = ("/".join(path.parts[skip_parts:]) for path in rel_paths)

    metafunc.parametrize(
        FIXTURE_NAME,
        ((path, metafunc.function) for path in paths),
        ids=ids,
        indirect=True,
    )


def pytest_assertion_pass(item, lineno, orig, expl):
    fixt = item.funcargs.get(FIXTURE_NAME)
    if isinstance(fixt, GoldenTestFixture) and fixt.update_goldens:
        fixt._records.append(_AssertionRecord(lineno))