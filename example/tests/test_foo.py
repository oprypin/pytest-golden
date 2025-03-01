import pytest
from foo import find_words, add1

@pytest.mark.golden_test("test_find_words/*.yml")
def test_find_words(golden):
    assert find_words(golden["input"]) == golden.out["output"]


@pytest.mark.golden_test("test_add1/*.yml")
def test_add1(golden):
    helper(add1(golden["input"]), golden.out["output"])


def helper(x, y):
    assert x == y
