"""
EM-203 + EM-206 — Governance renewal cooldown + settled-naming signal
(contracts/wave-m.md §3 Wave M4). Two faces of the SAME failure class: agents
keep re-doing things the town has already DECIDED because the world surfaces no
"settled" signal.

  EM-203 — an unchanged ACTIVE effect-rule (work_bonus / ubi / recharge_subsidy)
    re-passes endlessly (run-663: 35×/27×/19×). A new
    `world.governance.renewal_cooldown_ticks` (default 0 = pre-EM-203 behavior)
    rejects a RENEWAL of an active rule whose last activation is within the
    cooldown, with an "already active (settled)" reason so agents legislate
    something NEW. DEFAULT 0 keeps the W11b renewal-ritual byte-identical.

  EM-206 — `world.town_name` is surfaced as DECIDED/SETTLED in the prompt, and a
    no-op rename (proposed name == current, case-insensitive) is rejected with
    "already named X (settled)". Extends the EM-200/run-663 no-op guard.

Pure unit tests — no loop/provider/db. Construct the World directly.
"""
from __future__ import annotations

import yaml

from petridish.config.loader import (
    WorldParams,
    GovernanceParams,
    EMBEDDED_WORLD_YAML,
    _parse_governance,
    load_config,
)
from petridish.engine.world import AgentState, PlaceState, RuleState, World
from petridish.agents.runtime import _assemble_context


# ── fixtures ──────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=20, **overrides)


def _world(params: WorldParams | None = None) -> World:
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="townhall", name="Town Hall", x=0, y=10, kind="governance"),
    ]
    ada = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                     location="townhall", energy=80.0, credits=50)
    return World(params=params or _params(), places=places, agents=[ada])


def _active_rule(world: World, effect: str, created_tick: int,
                 renewed_at: list[int] | None = None) -> RuleState:
    rule = RuleState(
        id=f"r_{effect}_active", effect=effect, text=f"{effect} law",
        proposer_id="agent_ada", status="active", created_tick=created_tick,
        renewed_at=list(renewed_at or []),
    )
    world.rules[rule.id] = rule
    return rule


def _system_prompt(world: World, agent: AgentState) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── EM-203: renewal cooldown ──────────────────────────────────────────────────

def test_renewal_blocked_within_cooldown_with_settled_reason():
    """With a positive cooldown, re-proposing an ACTIVE effect whose last
    activation is within the window is rejected as already active (settled)."""
    world = _world(_params(governance=GovernanceParams(renewal_cooldown_ticks=50)))
    ada = world.agents["agent_ada"]
    _active_rule(world, "work_bonus", created_tick=100)
    world.tick = 120  # 20 < 50 → still settled

    ok, reason, rule = world.action_propose_rule(ada, "work_bonus", "Renew it")
    assert not ok, "a renewal within the cooldown must be rejected"
    assert rule is None
    assert "settled" in reason.lower(), reason
    assert "work_bonus" in reason.lower() or "already active" in reason.lower(), reason


def test_renewal_allowed_after_cooldown_elapses():
    """Once the cooldown has elapsed since the last activation, the renewal is
    allowed again (tagged renewal_of, the W11b ritual)."""
    world = _world(_params(governance=GovernanceParams(renewal_cooldown_ticks=50)))
    ada = world.agents["agent_ada"]
    active = _active_rule(world, "ubi", created_tick=100)
    world.tick = 100 + 50  # exactly at the boundary → allowed

    ok, reason, rule = world.action_propose_rule(ada, "ubi", "Renew it")
    assert ok, f"a renewal at/after the cooldown boundary must be allowed: {reason}"
    assert rule is not None and rule.renewal_of == active.id


def test_renewal_cooldown_counts_from_latest_renewal_not_creation():
    """The 'last activation' is the most recent of created_tick / renewed_at — a
    rule renewed recently is settled even if first created long ago."""
    world = _world(_params(governance=GovernanceParams(renewal_cooldown_ticks=50)))
    ada = world.agents["agent_ada"]
    _active_rule(world, "recharge_subsidy", created_tick=10, renewed_at=[200])
    world.tick = 230  # 30 since the last renewal (200) < 50 → settled

    ok, reason, rule = world.action_propose_rule(ada, "recharge_subsidy", "Renew")
    assert not ok and rule is None, "settled by the recent renewal, not creation"
    assert "settled" in reason.lower(), reason


def test_renewal_cooldown_default_zero_is_pre_em203_behavior():
    """DEFAULT cooldown 0 ⇒ NO renewal is ever blocked: the W11b renewal ritual
    (re-propose at the same tick) still tags renewal_of and succeeds."""
    world = _world()  # default governance → renewal_cooldown_ticks == 0
    ada = world.agents["agent_ada"]
    active = _active_rule(world, "work_bonus", created_tick=37)
    world.tick = 37  # same tick as activation — the W11b case

    ok, reason, rule = world.action_propose_rule(ada, "work_bonus", "Renew it")
    assert ok, f"default cooldown must not block any renewal: {reason}"
    assert rule is not None and rule.renewal_of == active.id


def test_renewal_cooldown_does_not_block_a_brand_new_effect():
    """The cooldown only guards RENEWALS of an active rule; proposing an effect
    with NO active counterpart is always allowed."""
    world = _world(_params(governance=GovernanceParams(renewal_cooldown_ticks=999)))
    ada = world.agents["agent_ada"]
    world.tick = 5

    ok, reason, rule = world.action_propose_rule(ada, "ubi", "Fresh law")
    assert ok and rule is not None and rule.renewal_of is None, reason


# ── EM-206: settled-naming signal ─────────────────────────────────────────────

def test_no_op_rename_rejected_with_settled_message():
    """A rename to the name the town already holds is rejected with the settled
    phrasing (extends the EM-200/run-663 no-op guard)."""
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"

    ok, reason, rule = world.action_propose_rule(
        ada, "name_town", "Rename", name="Ledger's Folly")
    assert not ok and rule is None
    # Keep the EM-200 substring ("already named") AND add the settled flag.
    assert "already named" in reason.lower(), reason
    assert "settled" in reason.lower(), reason
    assert "Ledger's Folly" in reason, reason


def test_no_op_rename_settled_message_is_case_and_space_insensitive():
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"

    ok, reason, _ = world.action_propose_rule(
        ada, "name_town", "Rename", name="  LEDGER'S FOLLY  ")
    assert not ok, "case/space variants of the current name stay no-ops"
    assert "settled" in reason.lower(), reason


def test_genuinely_new_name_still_allowed():
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Ledger's Folly"

    ok, _, rule = world.action_propose_rule(
        ada, "name_town", "Rebrand", name="Ledger's Fortune")
    assert ok and rule is not None, "a real rename must still pass the guard"


def test_town_name_settled_signal_present_in_prompt_context():
    """Once named, the prompt marks the town name as DECIDED/SETTLED so agents
    stop campaigning to (re)name what they already hold."""
    world = _world()
    ada = world.agents["agent_ada"]
    world.town_name = "Hopewell"

    sp = _system_prompt(world, ada)
    assert "Hopewell" in sp
    assert "settled" in sp.lower(), "the town name must be flagged as settled/decided"


def test_unnamed_town_adds_no_settled_line_golden_safe():
    """An UNNAMED town surfaces NOTHING new — naming stays emergent and the
    em161 golden for a default agent is unaffected."""
    world = _world()
    ada = world.agents["agent_ada"]
    assert world.town_name == ""

    sp = _system_prompt(world, ada)
    assert "settled" not in sp.lower()
    assert "Town:" not in sp


# ── config: GovernanceParams parse + absent block ─────────────────────────────

def test_parse_governance_absent_block_is_default():
    assert _parse_governance(None) == GovernanceParams()
    assert _parse_governance(None).renewal_cooldown_ticks == 0


def test_parse_governance_reads_and_clamps():
    assert _parse_governance({"renewal_cooldown_ticks": 200}).renewal_cooldown_ticks == 200
    # negative clamps to 0 (a malformed value never breaks the block)
    assert _parse_governance({"renewal_cooldown_ticks": -5}).renewal_cooldown_ticks == 0
    assert _parse_governance({"renewal_cooldown_ticks": "nope"}).renewal_cooldown_ticks == 0


def test_governance_param_accessor_falls_back_when_block_absent():
    world = _world()
    # An absent/default block ⇒ the engine accessor returns the call-site default.
    assert world._governance_param("renewal_cooldown_ticks", 0) == 0


def test_embedded_yaml_governance_mirror_is_default_off():
    """The EMBEDDED_WORLD_YAML mirror carries a `governance` block that parses to
    the default (renewal_cooldown_ticks 0), so a world running off the embedded
    fallback stays byte-identical to pre-EM-203."""
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    gov = _parse_governance(raw["world"].get("governance"))
    assert gov == GovernanceParams()
    assert gov.renewal_cooldown_ticks == 0


def test_live_config_loads_a_governance_block():
    """The live config/world.yaml wires a GovernanceParams (the live run sets a
    positive cooldown to nudge new legislation)."""
    cfg = load_config()
    assert isinstance(cfg.world.governance, GovernanceParams)
    assert cfg.world.governance.renewal_cooldown_ticks >= 0
