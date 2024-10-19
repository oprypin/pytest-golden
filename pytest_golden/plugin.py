from __future__ import annotations

import contextlib
import dataclasses
import inspect
import logging
import pathlib
import warnings
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import atomicwrites
import pytest

from . import yaml

if TYPE_CHECKING:
    import os


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
    path = None
    try:
        path, func = request.param
    except AttributeError:
        func = request.function

    fixt = GoldenTestFixtureFactory(
        pathlib.Path(request.module.__file__),
        func,
        request.config.getoption("--update-goldens"),
        request.config.getini("enable_assertion_pass_hook"),
    )
    if path is not None:
        fixt = fixt.open(path)
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
class GoldenTestFixtureFactory:
    name = FIXTURE_NAME

    path: pathlib.Path
    func: Callable
    update_goldens: bool
    assertions_enabled: bool

    _fixtures: list[GoldenTestFixture] = dataclasses.field(init=False)

    def __post_init__(self):
        self._fixtures = []

    def open(self, path: os.PathLike) -> GoldenTestFixture:
        fixt = GoldenTestFixture(
            path=self.path.parent / path,
            func=self.func,
            update_goldens=self.update_goldens,
            assertions_enabled=self.assertions_enabled,
        )
        self._fixtures.append(fixt)
        return fixt

    def _add_record(self, r):
        for f in self._fixtures:
            f._add_record(r)

    def teardown(self, item):
        for f in self._fixtures:
            f.teardown(item)


@dataclasses.dataclass
class GoldenTestFixture(GoldenTestFixtureFactory):
    _used_fields: set[str] = dataclasses.field(init=False)
    _records: list[_ComparisonRecord | _AssertionRecord] = dataclasses.field(init=False)
    _inputs: dict[str, Any] = dataclasses.field(init=False)

    def __post_init__(self):
        self._used_fields = set()

        # Keep inputs as a separate copy, so if an input gets mutated, it isn't written back.
        with open(self.path, encoding="utf-8") as f:
            self._inputs = yaml._safe.load(f) or {}
        if not isinstance(self._inputs, dict):
            raise UsageError(f"The YAML file '{self.path}' must contain a dict at the top level.")

        if self.update_goldens:
            self.out = GoldenOutputProxy(self)
            self._records = []
        else:
            with open(self.path, encoding="utf-8") as f:
                self.out = yaml._safe.load(f) or {}

    def __getitem__(self, key: str) -> Any:
        self._used_fields.add(key)
        return self._inputs[key]

    def get(self, key: str, default: T | None = None) -> Any | T:
        self._used_fields.add(key)
        return self._inputs.get(key, default)

    def _add_record(self, r):
        self._records.append(r)

    def teardown(self, item) -> None:
        if not self.update_goldens:
            return

        actual: dict[str, _AbsentValue | Any] = {}
        approved_lines: set[int] = set()
        to_warn: list[tuple[str, _ComparisonRecord]] = []

        def warn(*args):
            return to_warn.append(args)

        for record in reversed(self._records):
            if isinstance(record, _AssertionRecord):
                approved_lines.add(record.lineno)
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

        yaml._prepare_for_output(actual)
        with open(self.path, encoding="utf-8") as f:
            outputs = yaml._rt.load(f) or {}
        for k, v in actual.items():
            if isinstance(v, _AbsentValue):
                outputs.pop(k, None)
            else:
                outputs[k] = v

        unused_fields = outputs.keys() - self._used_fields
        if unused_fields:
            f_code = self.func.__code__
            warnings.warn_explicit(
                f"Unused field(s) {', '.join(map(repr, sorted(unused_fields)))} in {item.name}",
                GoldenTestUsageWarning,
                f_code.co_filename,
                f_code.co_firstlineno,
            )
        with atomicwrites.atomic_write(self.path, mode="w", encoding="utf-8", overwrite=True) as f:
            yaml._rt.dump(outputs, f)

    @contextlib.contextmanager
    def may_raise(self, cls: type[Exception], *, key: str = "exception"):
        try:
            yield
        except cls as e:
            assert self.out.get(key) == {type(e).__name__: str(e)}
        else:
            assert self.out.get(key) is None

    @contextlib.contextmanager
    def capture_logs(
        self,
        loggers: str | tuple[str],
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

    def __getitem__(self, key: str) -> GoldenOutput:
        self.fixt._used_fields.add(key)
        return GoldenOutput(self.fixt, key)

    def get(self, key: str) -> GoldenOutput:
        self.fixt._used_fields.add(key)
        return GoldenOutput(self.fixt, key, optional=True)


@dataclasses.dataclass
class GoldenOutput:
    fixt: GoldenTestFixture
    key: str
    optional: bool = False

    @property
    def value(self):
        return self.fixt[self.key]

    def __eq__(self, other) -> GoldenComparison:  # type: ignore[override]
        if isinstance(other, GoldenOutput):
            raise TypeError("Can't compare two golden output placeholders")
        return GoldenComparison(self.fixt, self.key, other, self.optional)

    def __ne__(self, other) -> GoldenComparison:  # type: ignore[override]
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
            inspect.unwrap(self.fixt.func).__code__,
            inspect.unwrap(GoldenTestFixture.may_raise).__code__,
            inspect.unwrap(GoldenTestFixture.capture_logs).__code__,
        ]
        for info in stack:
            if info.frame.f_code in approved:
                self.fixt._add_record(_ComparisonRecord(self, inspect.getframeinfo(info.frame)))
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
    comparison: GoldenComparison
    location: inspect.Traceback

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


def pytest_generate_tests(metafunc) -> None:
    item = metafunc.definition
    marker = item.get_closest_marker(MARKER_NAME)
    if not marker:
        return
    patterns = _golden_test_marker(*marker.args, **marker.kwargs)

    f_code = metafunc.function.__code__

    def warn(msg):
        warnings.warn_explicit(
            f"{msg}: {metafunc.function}",
            GoldenTestUsageWarning,
            f_code.co_filename,
            f_code.co_firstlineno,
        )

    if FIXTURE_NAME not in metafunc.fixturenames:
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
    if all(
        "test_".removeprefix(path.parts[0]) == "test_".removeprefix(item.originalname)
        for path in rel_paths
    ):
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
    if isinstance(fixt, GoldenTestFixtureFactory) and fixt.update_goldens:
        fixt._add_record(_AssertionRecord(lineno))
