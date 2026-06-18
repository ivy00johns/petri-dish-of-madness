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


def test_looks_truncated_rejects_cutoffs_and_stubs():
    """EM-201 follow-on — the proxy reroutes the chronicler lane to models
    (nvidia/nemotron) that hit the token cap mid-sentence, or return a
    degenerate stub (the literal 'A' chapter seen live). Both survive
    _clean_chapter AND the reasoning guard, so the writer rejects them via
    _looks_truncated and leaves the window for a clean model / retry to fill."""
    # finish_reason == "length": the reply was cut off at the cap mid-generation
    assert TickLoop._looks_truncated(
        "The town gathered in the plaza as the vote", "length")
    # degenerate stubs: the 'A', a lone em-dash, an ellipsis, one terse word,
    # whitespace — none is a paragraph, all rejected regardless of finish_reason
    for stub in ("A", "—", "...", "Quiet.", "   "):
        assert TickLoop._looks_truncated(stub, "stop"), stub
    # real chapters PASS even when terse (the suite's shortest valid prose) and
    # even when the proxy omits finish_reason (None) — the floor stays well under
    # 9 words / 58 chars so a charming one-liner is never mistaken for a cutoff
    for clean in (
        "Ada was practically conducting an invisible orchestra of construction.",
        "First the sun rose over the plaza, then the schemes began.",
        "The town stirred, and the schemes began anew.",
    ):
        assert not TickLoop._looks_truncated(clean, "stop"), clean
        assert not TickLoop._looks_truncated(clean, None), clean


def test_build_chronicle_digest_picks_the_longest_quotes():
    """When many lines were spoken, the richest (longest) ones are surfaced."""
    rows = [
        {"kind": "agent_speech", "tick": t, "text": f'X says: "{msg}"',
         "payload": {"said": msg}}
        for t, msg in [(1, "hi"), (2, "yo"), (3, "a long and dramatic monologue about the cabal and its many crimes against the commons")]
    ]
    digest = TickLoop._build_chronicle_digest(rows, ["X"], 0, 5)
    assert "long and dramatic monologue" in digest


# ──────────────────────────────────────────────────────────────────────────────
# EM-201 follow-on — _build_chronicle_facts: server-computed `chaos` facts that
# are STAMPED into the narrator_summary payload (so OLD chapters render real
# stats instead of an all-zero client-side reconstruction).
# ──────────────────────────────────────────────────────────────────────────────

def test_build_chronicle_facts_surfaces_quotes_cast_laws_conflicts_deaths_counts():
    rows = [
        {"kind": "agent_speech", "tick": 10,
         "text": 'Vesper says: "Bankruptcy is just a rebranding opportunity, but winning? That is forever."',
         "payload": {"said": "Bankruptcy is just a rebranding opportunity, but winning? That is forever."}},
        {"kind": "agent_speech", "tick": 11,
         "text": 'Mox mutters: "The cabal walks among us."',
         "payload": {"said": "The cabal walks among us."}},
        {"kind": "agent_speech", "tick": 12,
         "text": 'Vesper proclaims: "Order!"',
         "payload": {"said": "Order!"}},
        {"kind": "rule_passed", "tick": 13,
         "text": "By vote, a Transparency Dividend (ubi) of 10 credits passes.", "payload": {}},
        {"kind": "town_named", "tick": 14, "text": "The town shall be called Ledger's Folly.",
         "payload": {}},
        {"kind": "conflict", "tick": 15, "text": "Bram insults Vesper!", "payload": {}},
        {"kind": "commitment_lapsed", "tick": 16, "text": "Mox broke a promise to Ada.",
         "payload": {}},
        {"kind": "agent_died", "tick": 17, "text": "Ada starved in the plaza.", "payload": {}},
    ]
    facts = TickLoop._build_chronicle_facts(rows, 0, 20)

    # quotes: top-3 by length, carry speaker + said.
    assert [q["said"] for q in facts["quotes"]][0].startswith("Bankruptcy is just")
    assert facts["quotes"][0]["speaker"] == "Vesper"
    assert all("speaker" in q and "said" in q for q in facts["quotes"])
    assert len(facts["quotes"]) == 3

    # cast: distinct speakers in first-seen order.
    assert facts["cast"] == ["Vesper", "Mox"]

    # laws = rule_passed + town_named texts.
    assert any("Transparency Dividend" in law for law in facts["laws"])
    assert any("Ledger's Folly" in law for law in facts["laws"])

    # conflicts = conflict + commitment_lapsed texts.
    assert any("insults" in c for c in facts["conflicts"])
    assert any("broke a promise" in c for c in facts["conflicts"])

    # deaths = agent_died texts.
    assert any("starved" in d for d in facts["deaths"])

    # the four counts agree with the contract definitions exactly.
    assert facts["counts"] == {"spoken": 3, "laws": 2, "clashes": 2, "deaths": 1}


def test_build_chronicle_facts_quiet_window_is_empty_lists_and_zero_counts():
    facts = TickLoop._build_chronicle_facts([], 30, 40)
    assert facts["cast"] == []
    assert facts["quotes"] == []
    assert facts["laws"] == []
    assert facts["conflicts"] == []
    assert facts["deaths"] == []
    assert facts["counts"] == {"spoken": 0, "laws": 0, "clashes": 0, "deaths": 0}


def test_build_chronicle_facts_speaker_falls_back_to_actor_then_dash():
    rows = [
        # no recognizable speech verb in text → fall back to actor_id.
        {"kind": "agent_speech", "tick": 1, "text": "(garbled transmission)",
         "actor_id": "agent_zed", "payload": {"said": "zzz"}},
        # no verb, no actor → the em-dash sentinel.
        {"kind": "agent_speech", "tick": 2, "text": "...", "payload": {"said": "..."}},
    ]
    facts = TickLoop._build_chronicle_facts(rows, 0, 5)
    assert "agent_zed" in facts["cast"]
    assert "—" in facts["cast"]


def test_build_chronicle_facts_said_strips_prefix_when_no_payload():
    """said(ev) uses payload.said when present, else strips the 'Name verb[,:]'
    prefix off ev.text."""
    rows = [
        {"kind": "agent_speech", "tick": 1,
         "text": 'Ada declares: The festival begins!', "payload": {}},
    ]
    facts = TickLoop._build_chronicle_facts(rows, 0, 5)
    assert facts["quotes"][0]["speaker"] == "Ada"
    assert facts["quotes"][0]["said"] == "The festival begins!"
