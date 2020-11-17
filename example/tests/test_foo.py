import pytest
from foo import find_words

@pytest.mark.golden_test("test_find_words/*.yml")
def test_find_words(golden):
    assert find_words(golden["input"]) == golden.out["output"]
