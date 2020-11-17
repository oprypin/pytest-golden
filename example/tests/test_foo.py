from foo import find_words

def test_find_words(golden):
    golden = golden.open("test_find_words/test_basic.yml")
    assert find_words(golden["input"]) == golden.out["output"]
