import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import project_paths  # noqa: E402,F401  (puts every src/* package dir on sys.path)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_scenario_registry():
    """The dashboard (and tests/test_expansion.py) add the 17 expansion scenarios to the global
    registries at runtime; undo that after every test so other tests still see the approved 20."""
    import feature_extraction
    import scenario_definitions
    reg = list(scenario_definitions.SCENARIO_REGISTRY)
    kb = dict(feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE)
    yield
    scenario_definitions.SCENARIO_REGISTRY[:] = reg
    feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE.clear()
    feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE.update(kb)
