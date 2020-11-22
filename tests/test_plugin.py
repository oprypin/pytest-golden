import warnings

import pytest

from pytest_golden import plugin


@pytest.mark.golden_test("full/test_*.yml")
@pytest.mark.parametrize("upd", [False, True])
def test_full(testdir, golden, upd):
    assert golden.path.stem in golden["test"]

    testdir.makefile(".ini", pytest="[pytest]\nenable_assertion_pass_hook=true\n")
    testdir.makepyfile(golden["test"])

    files = golden.get("files") or {}
    for name, content in files.items():
        (testdir.tmpdir / name).write_text(content, encoding="utf-8")

    with pytest.warns(plugin.GoldenTestUsageWarning) as record:
        warnings.warn("OK", plugin.GoldenTestUsageWarning)
        result = testdir.runpytest(*(("--update-goldens",) if upd else ()))

    assert ([str(w.message) for w in record[1:]] or None) == golden.out.get("warnings")

    new_files = {}
    for k, v in files.items():
        content = (testdir.tmpdir / k).read_text(encoding="utf-8")
        if upd and content == v:
            continue
        new_files[k] = content
    updated_files_golden = golden.out.get("updated_files")
    if upd:
        assert (new_files or None) == updated_files_golden
    else:
        assert new_files == files

    outcomes = (golden.out["outcomes"], golden.out["outcomes_update"])
    assert result.parseoutcomes() == outcomes[upd]

    if golden.get("match_output"):
        result.stdout.fnmatch_lines(["*" + l + "*" for l in golden["match_output"]])
