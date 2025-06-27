By default, this package is configured to run PyTest tests
(http://pytest.org/).

## Writing tests

Place test files in this directory, using file names that start with `test_`.

## Running tests

```
$ make test
```

Or using the test environment script:

```
$ SKIP_VENV_GLP_TESTING=1 test/test-in-venv.sh make test
```

To run pytest directly with options:

```
$ python -m pytest [pytest options]
```

For example, to run a single test or subset of tests:

```
$ python -m pytest -k TEST_PATTERN
```

Code coverage is automatically reported for git_llm_pick;
to add other packages, modify setup.cfg in the package root directory.

To debug failing tests:

```
$ python -m pytest --pdb
```

This will drop you into the Python debugger on the failed test.

### Importing tests/fixtures

The `test` module is generally not direcrtly importable and it's generally acceptable to use relative imports inside test cases.

### Fixtures

Pytest provides `conftest.py` as a mechanism to store test fixtures.  However, there may be times when it makes sense to include a `test/fixtures` module to locate complex or large fixtures.

### Common Errors

#### ModuleNotFoundError: No module named "test.fixtures"

The `test` and sometimes `test/fixtures` modules need to be importable.  To allow these to be importable, create a `__init__.py` file in each directory.
- `test/__init__.py`
- `test/fixtures/__init__.py` (optional)
