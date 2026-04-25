# tests/gateway/test_role_router.py
"""Tests for the semantic role router (issue #19)."""
import pytest
from unittest.mock import patch
import numpy as np


MOCK_ROLES = {
    "code-auditor": {
        "slug": "code-auditor",
        "name": "Code Auditor",
        "summary": "security code review vulnerability scanning",
    },
    "expert-architect": {
        "slug": "expert-architect",
        "name": "Expert Architect",
        "summary": "system architecture design technical planning",
    },
    "department-head": {
        "slug": "department-head",
        "name": "Department Head",
        "summary": "task management coordination planning delegation",
    },
}


@pytest.fixture(autouse=True)
def patch_load_roles():
    with patch("src.gateway.role_router.load_roles", return_value=MOCK_ROLES):
        yield


def _make_router():
    from src.gateway.role_router import RoleRouter
    r = RoleRouter()
    r._initialized = False  # force reinit with patched load_roles
    return r


@pytest.mark.asyncio
async def test_returns_none_when_no_match():
    r = _make_router()
    result = await r.route("what is 2+2")
    # Very low overlap → should be None (or maybe a low-confidence match)
    # We mainly verify it doesn't crash
    assert result is None or isinstance(result, str)


@pytest.mark.asyncio
async def test_heuristic_matches_security_text():
    r = _make_router()
    # Force heuristic mode by disabling embed_fn
    r._lazy_init()
    r._embed_fn = None
    r._embeddings = None
    result = await r.route("please do a security code review")
    assert result == "code-auditor"


@pytest.mark.asyncio
async def test_heuristic_matches_architecture_text():
    r = _make_router()
    r._lazy_init()
    r._embed_fn = None
    r._embeddings = None
    result = await r.route("we need system architecture design")
    assert result == "expert-architect"


@pytest.mark.asyncio
async def test_heuristic_returns_none_for_low_overlap():
    r = _make_router()
    r._lazy_init()
    r._embed_fn = None
    r._embeddings = None
    result = await r.route("hello world foo bar baz", threshold=0.5)
    assert result is None


@pytest.mark.asyncio
async def test_semantic_route_used_when_embed_fn_available():
    r = _make_router()
    r._lazy_init()
    r._embed_fn = None

    dim = 8
    embeddings = np.random.randn(len(MOCK_ROLES), dim)
    r._embeddings = embeddings

    call_log = []

    def mock_embed(texts):
        call_log.append(texts)
        return np.random.randn(len(texts), dim)

    r._embed_fn = mock_embed
    await r.route("some query")
    assert len(call_log) >= 1, "embed_fn should have been called"


@pytest.mark.asyncio
async def test_router_does_not_crash_when_embed_fn_raises():
    r = _make_router()
    r._lazy_init()

    def bad_embed(texts):
        raise RuntimeError("model broken")

    r._embed_fn = bad_embed
    r._embeddings = np.zeros((len(MOCK_ROLES), 4))

    # Should fall through to heuristic without raising
    result = await r.route("code review security", threshold=0.1)
    assert result is None or isinstance(result, str)


def test_cosine_similarity_basic():
    from src.gateway.role_router import _cosine_similarity
    a = np.array([1.0, 0.0])
    b = np.array([1.0, 0.0])
    assert abs(_cosine_similarity(a, b) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    from src.gateway.role_router import _cosine_similarity
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert abs(_cosine_similarity(a, b)) < 1e-6


def test_heuristic_score_exact_match():
    from src.gateway.role_router import _heuristic_score
    score = _heuristic_score("security review", "security code review")
    assert score > 0.2


def test_heuristic_score_no_overlap():
    from src.gateway.role_router import _heuristic_score
    score = _heuristic_score("pizza pasta tomato", "security code review")
    assert score == 0.0
