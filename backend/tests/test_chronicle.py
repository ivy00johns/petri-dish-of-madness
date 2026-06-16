"""
Chronicle (EM-201) — the narrator grown into a chronicler of the emergent saga.

The thin EM-094 recap digest (deaths/rules/projects/conflicts, counts + last 20
lines) is enriched into a rich chapter digest that surfaces the DRAMA the run
produced: memorable spoken lines, the laws passed, the cast, and conflict —
the material that made the run-663 review GOLD. `_build_chronicle_digest` is a
pure function over event rows so it is unit-testable without driving the loop.
"""
from __future__ import annotations

from petridish.engine.loop import TickLoop


def _rows():
    return [
        {"kind": "agent_speech", "tick": 10,
         "text": 'Vesper says: "Bankruptcy is just a rebranding opportunity, but winning? That is forever."',
         "payload": {"said": "Bankruptcy is just a rebranding opportunity, but winning? That is forever."}},
        {"kind": "agent_speech", "tick": 11,
         "text": 'Mox says: "The cabal walks among us."',
         "payload": {"said": "The cabal walks among us."}},
        {"kind": "rule_passed", "tick": 12,
         "text": "By vote, a Transparency Dividend (ubi) of 10 credits passes.",
         "payload": {"effect": "ubi"}},
        {"kind": "conflict", "tick": 13, "text": "Bram insults Vesper!", "payload": {}},
        {"kind": "agent_died", "tick": 14, "text": "Nobody died here.", "payload": {}},
    ]


def test_build_chronicle_digest_surfaces_quotes_laws_cast_and_drama():
    digest = TickLoop._build_chronicle_digest(_rows(), ["Vesper", "Mox", "Bram"], 0, 20)
    # a memorable spoken line (the chat — EXCLUDED by the old digest)
    assert "Bankruptcy is just a rebranding" in digest
    # the law that passed
    assert "ubi" in digest or "Transparency Dividend" in digest
    # the living cast
    assert "Vesper" in digest and "Mox" in digest
    # the conflict
    assert "insults" in digest
    # the window framing
    assert "0" in digest and "20" in digest


def test_build_chronicle_digest_handles_a_quiet_window():
    """No speech / laws / drama → still a valid, non-empty digest (charm, not a crash)."""
    digest = TickLoop._build_chronicle_digest([], ["Ada"], 30, 40)
    assert isinstance(digest, str) and digest.strip()
    assert "Ada" in digest


def test_build_chronicle_digest_picks_the_longest_quotes():
    """When many lines were spoken, the richest (longest) ones are surfaced."""
    rows = [
        {"kind": "agent_speech", "tick": t, "text": f'X says: "{msg}"',
         "payload": {"said": msg}}
        for t, msg in [(1, "hi"), (2, "yo"), (3, "a long and dramatic monologue about the cabal and its many crimes against the commons")]
    ]
    digest = TickLoop._build_chronicle_digest(rows, ["X"], 0, 5)
    assert "long and dramatic monologue" in digest
