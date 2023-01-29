# pytest-golden

**Plugin for [pytest] that offloads expected outputs to data files**

[![PyPI](https://img.shields.io/pypi/v/pytest-golden)](https://pypi.org/project/pytest-golden/)
[![GitHub](https://img.shields.io/github/license/oprypin/pytest-golden)](https://github.com/oprypin/pytest-golden/blob/master/LICENSE.md)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/oprypin/pytest-golden/ci.yml.svg)](https://github.com/oprypin/pytest-golden/actions?query=event%3Apush+branch%3Amaster)

[pytest]: https://pytest.org/

## Usage, in short

(see also: [example/](example/))

[Install the pytest plugin](https://docs.pytest.org/en/latest/plugins.html):

```shell
pip install pytest-golden
```

Create a test file (e.g. *tests/test_foo.py*):

```python
@pytest.mark.golden_test("test_bar/*.yml")
def test_bar(golden):
    assert foo.bar(golden["input"]) == golden.out["output"]
```

The wildcard selects the "golden" files which serve as both the input and the expected output for the test. The test is basically parameterized on the files.

Create one or more of such YAML files (e.g. *tests/test_bar/basic.yml*):

```yaml
input: Abc
output: Nop
```

Run `pytest` to execute the test(s).

Whenever the function under test gets changed, its result may change as well, and the test won't pass anymore. You can run `pytest --update-goldens` to automatically re-populate the output.

**See [detailed usage](#usage).**

## The case for golden testing

Consider this normal situation when testing a function (e.g. a function to list all words in a sentence).

#### *foo.py*

```python
def find_words(text: str) -> list:
    return text.split()
```

#### *tests/test_foo.py*

```python
from foo import find_words

def test_find_words():
    assert find_words("If at first you don't succeed, try, try again.") == [
        "If", "at", "first", "you", "don't", "succeed,", "try,", "try", "again."
    ]
```

You wrote a basic test for that function, but it can be quite tedious to manually write out what the expected output is, especially if the output was something bigger. Sometimes perhaps you'd resort to just writing a dummy test first and copying the actual output from the failure message. And there's nothing really wrong with that, because then you'd still manually inspect whether the new output is good.

### With golden testing

But let's rewrite this test using "golden testing".

#### *tests/test_foo.py*

```python
from foo import find_words

def test_find_words(golden):
    golden = golden.open("test_find_words/test_basic.yml")
    assert find_words(golden["input"]) == golden.out["output"]
```

Here `golden["xxx"]` will be a value read directly from the associated file. Let's create that (YAML) file:

#### *tests/test_find_words/test_basic.yml*

```yaml
input: |-
  If at first you don't succeed, try, try again.
```

Unlike the input, `golden.out["yyy"]` works a little differently. Normally it will also be just an input for the test, taken from the file (and the assertion will be a completely normal [pytest][] assertion), but in a special "update" mode it will instead accept whatever the result is at runtime and put it back into the "golden" file. Both updating and initially populating the file is done automatically with the command **`pytest --update-goldens`**:

#### *tests/test_find_words/test_basic.yml*

```yaml
input: |-
  If at first you don't succeed, try, try again.
output:
- If
- at
- first
- you
- don't
- succeed,
- try,
- try
- again.
```

Now, when running just `pytest`, the test will always assert that the result is exactly equal to the expected output. Which is just how unittests work.

Now you can add all of this into your source control system.

### Introducing a change

Let's say you're not happy that the punctuation gets clumped with the words, so you devise a different implementation for this function.

#### *foo.py*

```python
import re

def find_words(text: str) -> list:
    return re.findall(r"\w+", text)
```

You also want to add another test case for it:

#### *tests/test_find_words/test_quotation.yml*

```yaml
input: |-
  Dr. King said, 'I have a dream.'
output:
- Dr
- King
- said
- I
- have
- a
- dream
```

And let's just turn this into a *parameterized* golden test (one test generated per each file that matches the wildcard):

#### *tests/test_foo.py*

```python
import pytest
from foo import find_words

@pytest.mark.golden_test("test_find_words/*.yml")
def test_find_words(golden):
    assert find_words(golden["input"]) == golden.out["output"]
```

Now if we run `pytest -v`, we see that all is well with the new test, which gets picked up as `test_find_words[test_quotation.yml]`, but the code changes also made it so the previous test now disagrees! You get a normal failure message from *pytest* itself.

Normally in such situations you'd go back to the test file and edit the expected output (if you indeed expected it to change). But with this you can instead just run `pytest --update-goldens`, and you'll see that instead the "golden" file gets updated by itself (with no test failure). The resulting diff can then still be viewed in your source control system:

```diff
--- a/tests/test_find_words/test_basic.yml
+++ b/tests/test_find_words/test_basic.yml
@@ -5,8 +5,9 @@ output:
 - at
 - first
 - you
-- don't
-- succeed,
-- try,
+- don
+- t
+- succeed
 - try
-- again.
+- try
+- again
```

Now you (and potentially your code reviewers) get to decide whether this diff is an acceptable one, or whether more changes are needed. You can do another iteration on the code, and the unittest will get updated as you go, and you never need to manually edit it -- just visually inspect the changes and check them in.

## Usage

### `golden` fixture

Add a `golden` parameter to your [pytest][] test function, and it will be passed a `GoldenTestFixtureFactory`.

### class `GoldenTestFixtureFactory`

#### `golden.open(path) -> GoldenTestFixture`

Call this method on the `golden` object to get an actual usable [fixture](#class-goldentestfixture).

The `path` argument is a path to a file, relative to the calling Python test file. Teardown is done automatically when the test function finishes.

### `@pytest.mark.golden_test(*patterns: str)`

Use this decorator to:

1. avoid having to call `.open` and get a [proper fixture](#class-goldentestfixture) directly as the `golden` argument of your test function and
2. add parameterization to your "golden" test.

The `patterns` are one or more [glob patterns](https://docs.python.org/3/library/pathlib.html#pathlib.Path.glob), relative to the calling Python test file. One test will be created for each matched file.

### class `GoldenTestFixture`

#### `golden[input_key: str] -> Any`

Get a value from the associated YAML file, at the top-level key. May raise `KeyError`.

#### `golden.get(input_key: str) -> Optional[Any]`

Ditto, but returns `None` if the key is missing.

#### `golden.out[output_key: str] -> Any`

* In normal mode:

  Get a value from the associated YAML file, at the top-level key. May raise `KeyError`.

* If `--update-goldens` flag is passed:

  Get a proxy object for the key, which, upon being compared for equality (and subsequently asserted on), marks that the "golden" file should get an updated value for this top-level key. Such updates get performed upon teardown of the fixture: the original file always gets rewritten once.

#### `golden.out.get(output_key: str) -> Optional[Any]`

Ditto, but when compared to `None`, marks the key as deleted from the file, rather than just having the value `None`.

## How to...

### Make a custom type representable in YAML

We will make these types known to the underlying implementation -- [ruamel.yaml](https://yaml.readthedocs.io/), but let's use only the passthrough functions provided by the module `pytest_golden.yaml`. It is best to apply this globally, in *conftest.py*.

```python
import pytest_golden.yaml

pytest_golden.yaml.register_class(MyClass)
```

(and see [details for `ruamel.yaml`](https://yaml.readthedocs.io/en/latest/dumpcls.html))

Alternate example if your class is equivalent to a single value:

```python
class MyClass:
    def __init__(self, value: str):
        self.value = value

pytest_golden.yaml.add_representer(MyClass, lambda dumper, data: dumper.represent_scalar("!MyClass", data.value))
pytest_golden.yaml.add_constructor('!MyClass', lambda loader, node: MyClass(node.value))
```

Or in the particular case of subclassing a standard type, you could just drop the tag altogether and rely on equality to the base type.

```python
class MyClass(str):
    pass

pytest_golden.yaml.add_representer(MyClass, lambda dumper, data: dumper.represent_str(data))
```

### Apply a default golden file for all tests in a module

Consider this test where we use `pytest_golden` only for storing the outputs:

NOTE: These `*.yml` files need to be manually created first, even if empty.

```python
def test_foo(golden):
    golden = golden.open("stuff/test_foo.yml")
    assert foo() == golden.out["output"]

def test_bar(golden):
    golden = golden.open("stuff/test_bar.yml")
    assert bar("a", "b") == golden.out["output"]
```

The test bodies are different (so applying a pattern via a `mark` is not applicable), but we still want to automatically assign the golden files without repeating ourselves.

To do that, we can augment the `golden` fixture like this:

```python
@pytest.fixture
def my_golden(request, golden):
    return golden.open(f"stuff/{request.node.name}.yml")

def test_foo(my_golden):
    assert foo() == my_golden.out["output"]

def test_bar(my_golden):
    assert bar("a", "b") == my_golden.out["output"]
```

Here the name of the YAML files is based on the test name. Previously the file names were manually ensured to match. So these two snippets are fully equivalent.

Note that you don't even need to come up with a separate name like `my_golden` and just overwrite the original `golden` fixture for the whole module.

See [a real example of this](https://github.com/oprypin/mkdocs-gen-files/tree/233486840c8f8e5d3e86c1c0bf9032d758818406/tests).
