"""EM-313 — Fingerprint Ticker (behavioral stylometry, zero-LLM).

A pure-math, deterministic, VERSIONED classifier that infers which model an
agent is running from its behavior in the event log alone — verb-mix, build-vs-
talk ratio, JSON-retry rate, and sentence-length statistics. It compares an
agent's accumulating behavioral fingerprint against per-model reference
centroids mined from the event-sourced run.sqlite (historical runs, or — on a
fresh DB with no history — the other agents in the same run, leave-one-agent-out
so the inference is never circular).

This is FEED/VIEWER chrome. It is strictly READ-ONLY over the event log: it
NEVER writes events, never touches the tick loop, and produces zero sim
feedback, so it sits entirely off the replay/determinism surface. Nothing here
is consulted by the engine.

`FEATURE_VERSION` versions the feature extraction: bump it whenever the feature
math changes so retro-scores across releases stay comparable/auditable (the #1
risk called out in the source design). The whole pipeline is a pure function of
the event log + FEATURE_VERSION, so it is replay-safe / seeded-by-construction.
"""

from .classifier import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    build_centroids,
    classify,
    compute_run_fingerprints,
    features_from_turns,
    turns_from_events,
)

__all__ = [
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "build_centroids",
    "classify",
    "compute_run_fingerprints",
    "features_from_turns",
    "turns_from_events",
]
