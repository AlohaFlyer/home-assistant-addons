import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def fx():
    def load(name):
        return open(os.path.join(FIX, name), encoding="utf-8").read()
    return load
