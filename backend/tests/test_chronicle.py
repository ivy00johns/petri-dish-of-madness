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


def test_guard_rejects_leaked_reasoning_keeps_clean_prose():
    """EM-201 — a reasoning model (deepseek-v4-pro) intermittently emits its
    chain of thought instead of the chapter. The guard rejects those and keeps
    real prose, so a garbage 'chapter' is never stored."""
    leak = ("The chronicler must write the next chapter based on the digest. "
            "The task is to generate one or two vivid paragraphs in past tense.")
    assert TickLoop._looks_like_leaked_reasoning(leak)
    for t in (
        "Let me draft a first paragraph: the town stirred.",
        "Okay, let me write the chapter.",
        "I need to capture the drama of this stretch.",
        "Based on the digest, this was a quiet stretch.",
        "I'll write about Ada and the refreshments stand.",
        # the actual leak forms seen in the live run (deepseek AND qwen, via reroute):
        "Thinking. 1.  **Analyze the Request:**     *   **Role:** Chronicler of a tiny living town of AI agents.",
        "We are given a \"digest\" of the latest stretch (ticks 300-400) and the previous chapter. We need to write.",
    ):
        assert TickLoop._looks_like_leaked_reasoning(t), t
    # the GORGEOUS clean chapters (deepseek + qwen) must PASS the guard.
    for clean in (
        "The second hundred ticks of Ledger's Folly unfolded like a farce staged by actors.",
        "The neon pink of Ledger's Folly pulsed like a wound dressing the town's freshly stitched identity.",
        "The air in Ledger's Folly thrummed with a manic certainty as the final vote sealed the name.",
        "Ada was practically conducting an invisible orchestra of construction.",
        "First the sun rose over the plaza, then the schemes began.",  # not "first, i"
    ):
        assert not TickLoop._looks_like_leaked_reasoning(clean), clean


def test_clean_chapter_strips_think_blocks_and_titles():
    assert TickLoop._clean_chapter(
        "<think>I should write about Ada.</think>The town stirred.") == "The town stirred."
    assert TickLoop._clean_chapter("  The town stirred.  ") == "The town stirred."
    # a leading markdown title line is dropped, prose kept
    assert TickLoop._clean_chapter("## Chapter 5\nThe town awoke.") == "The town awoke."


def test_build_chronicle_digest_picks_the_longest_quotes():
    """When many lines were spoken, the richest (longest) ones are surfaced."""
    rows = [
        {"kind": "agent_speech", "tick": t, "text": f'X says: "{msg}"',
         "payload": {"said": msg}}
        for t, msg in [(1, "hi"), (2, "yo"), (3, "a long and dramatic monologue about the cabal and its many crimes against the commons")]
    ]
    digest = TickLoop._build_chronicle_digest(rows, ["X"], 0, 5)
    assert "long and dramatic monologue" in digest
