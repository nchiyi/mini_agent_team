import pytest
from src.agent_team.models import TaskMode


def test_classify_default_p7():
    from src.agent_team.classifier import classify
    mode, task = classify("build something")
    assert mode == TaskMode.P7
    assert task == "build something"


def test_classify_p9_lowercase():
    from src.agent_team.classifier import classify
    mode, task = classify("p9 refactor the auth module")
    assert mode == TaskMode.P9
    assert task == "refactor the auth module"


def test_classify_p9_uppercase():
    from src.agent_team.classifier import classify
    mode, task = classify("P9 build X")
    assert mode == TaskMode.P9
    assert task == "build X"


def test_classify_p10():
    from src.agent_team.classifier import classify
    mode, task = classify("p10 design the caching layer")
    assert mode == TaskMode.P10
    assert task == "design the caching layer"


def test_classify_empty_string():
    from src.agent_team.classifier import classify
    mode, task = classify("")
    assert mode == TaskMode.P7
    assert task == ""


def test_classify_p9_no_task():
    from src.agent_team.classifier import classify
    # "p9" with no following text: strip gives "p9", not "p9 " so falls through to P7
    mode, task = classify("p9")
    assert mode == TaskMode.P7
    assert task == "p9"
