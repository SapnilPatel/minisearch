"""Smoke test — proves the package imports and CI actually runs something.

Deliberately trivial. Its job is to fail loudly if the package layout or the CI
pipeline is broken, so every later milestone starts from a known-green baseline.
"""

import minisearch


def test_package_imports():
    assert minisearch.__version__ == "0.1.0"
