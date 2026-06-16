"""
Run-663 governance findings — the two High-severity bugs the 3-day live run
surfaced (4,974 ticks):

  1. PHANTOM NUMERIC RULE IDS — `uuid4().hex[:8]` occasionally yields an
     all-numeric string (the run's culprits 36219503 / 54031153 are all digits).
     The model then JSON-encodes its vote's `rule_id` as a NUMBER, and
     `world.rules.get(36219503)` (int) misses the `"36219503"` (str) key →
     "unknown rule" (206 failed votes; one ghost rule even renamed the town).

  2. NAME_TOWN RENAME LOOP — `name_town` had no check that the proposed name
     differs from the current town name, so "Ledger's Folly" re-passed 119 times
     (53% of all "laws" were no-op renames).
"""
from __future__ import annotations

from petridish.config.loader import WorldParams
from petridish.engine.world import AgentState, PlaceState, RuleState, World
from petridish.agents.runtime import _normalize_args


def _world() -> World:
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="townhall", name="Town Hall", x=0, y=10, kind="governance"),
    ]
    ada = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                     location="townhall", energy=80, credits=50)
    return World(params=WorldParams(tick_interval_seconds=0.5, turns_per_day=20),
                 places=places, agents=[ada])


# ── Bug 1: phantom numeric rule IDs ───────────────────────────────────────────

def test_new_rule_ids_are_never_all_numeric():
    """A freshly minted rule id must never be a bare all-numeric string, so the
    model can't JSON-encode it as an int when voting."""
    world = _world()
    ada = world.agents["agent_ada"]
    for effect in ("ubi", "ban_stealing", "work_bonus"):
        ok, _, rule = world.action_propose_rule(ada, effect, f"text for {effect}")
        assert ok and rule is not None
        assert not rule.id.isdigit(), f"rule id {rule.id!r} is all-numeric (votable-as-int)"
        del world.rules[rule.id]  # clear the duplicate-effect guard for the next


def test_vote_with_integer_rule_id_resolves():
    """The model sends `rule_id` as a JSON number; _normalize_args coerces it to
    a string so the lookup hits the string-keyed rule instead of 'unknown rule'.
    (Covers historical all-numeric ids already on disk.)"""
    world = _world()
    ada = world.agents["agent_ada"]
    world.rules["36219503"] = RuleState(
        id="36219503", effect="ubi", text="UBI", proposer_id=ada.id, created_tick=0)
    action = {"action": "vote", "args": {"rule_id": 36219503, "choice": True}}
    _normalize_args(action, ada, world)
    assert action["args"]["rule_id"] == "36219503", "int rule_id not coerced to str"
    ok, reason, _ = world.action_vote(ada, action["args"]["rule_id"], True)
    assert ok, f"vote on a numeric-id rule failed: {reason}"
    assert world.rules["36219503"].votes.get(ada.id) is True


# ── Bug 2: name_town rename loop ──────────────────────────────────────────────

def test_name_town_rejects_no_op_rename():
    """Proposing the name the town ALREADY has is a no-op and must be rejected,
    so the same rename can't re-pass forever (Ledger's Folly ×119)."""
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"
    ok, reason, _ = world.action_propose_rule(
        ada, "name_town", "Rename it", name="Ledger's Folly")
    assert not ok, "a no-op rename to the current name should be rejected"
    assert "already named" in reason.lower(), reason


def test_name_town_no_op_check_is_case_and_space_insensitive():
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"
    ok, _, _ = world.action_propose_rule(
        ada, "name_town", "Rename it", name="  ledger's folly  ")
    assert not ok, "case/space variants of the current name are still no-ops"


def test_name_town_allows_a_genuinely_new_name():
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"
    ok, _, rule = world.action_propose_rule(
        ada, "name_town", "Rebrand", name="Ledger's Fortune")
    assert ok and rule is not None, "a real rename must still be allowed"
