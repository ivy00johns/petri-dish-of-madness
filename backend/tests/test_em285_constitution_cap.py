"""EM-285 (W29) — the constitution block rides EVERY prompt, so it must be
bounded: dedupe by article text and render at most the N most-recent unique
articles (the header still reports the TRUE total). Unbounded ratified-article
growth was pure per-prompt token waste vs the max-call-rate north star.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context, _CONSTITUTION_RENDER_MAX


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(articles):
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance")]
    agent = AgentState(id="dot", name="Dot", personality="civic", profile="mock",
                       location="townhall", energy=80.0, credits=20)
    w = World(params=_params(), places=places, agents=[agent])
    w.constitution = list(articles)
    return agent, w


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _article(i, text=None):
    return {"id": f"art-{i}", "text": text or f"Article {i}: rule number {i}.",
            "ratified_tick": i}


def _block(sys: str) -> str:
    return sys.split("THE CONSTITUTION")[1].split("===", 1)[1].split("===", 1)[0]


# ── cap: only the N most-recent articles render; the header keeps the true total ─

def test_render_capped_to_most_recent_n():
    n = _CONSTITUTION_RENDER_MAX
    articles = [_article(i) for i in range(1, n + 4)]   # n+3 articles total
    agent, w = _world(articles)
    sys = _sys(agent, w)
    block = _block(sys)
    # Header reports the TRUE total plus the "showing N newest" note.
    assert f"THE CONSTITUTION ({n + 3} articles, showing {n} newest)" in sys
    # Exactly N article bullets render.
    assert block.count("  • ") == n
    # The newest N are kept; the oldest three (1,2,3) are dropped.
    assert f"rule number {n + 3}." in block
    assert "Article 1: rule number 1." not in block
    assert "Article 3: rule number 3." not in block
    assert "Article 4: rule number 4." in block   # first kept (oldest of the newest N)


# ── dedupe: a repeated article text renders once ──────────────────────────────

def test_duplicate_article_text_renders_once():
    dupe = "Article: no cars downtown."
    articles = [_article(1, dupe), _article(2, "Article: free markets."),
                _article(3, dupe)]
    agent, w = _world(articles)
    block = _block(_sys(agent, w))
    assert block.count(dupe) == 1
    assert block.count("Article: free markets.") == 1
    # Header keeps the TRUE stored total (3) and flags that fewer actually render.
    assert "THE CONSTITUTION (3 articles, showing 2 newest)" in _sys(agent, w)


# ── under the cap with no dupes: byte-shape unchanged (no "showing" note) ──────

def test_small_constitution_has_no_showing_note():
    agent, w = _world([_article(1), _article(2)])
    sys = _sys(agent, w)
    assert "THE CONSTITUTION (2 articles)" in sys
    assert "showing" not in _block(sys)
    assert _block(sys).count("  • ") == 2


def test_single_article_singular_header():
    agent, w = _world([_article(1, "Article I: all are free.")])
    sys = _sys(agent, w)
    assert "THE CONSTITUTION (1 article)" in sys
    assert "Article I: all are free." in sys
