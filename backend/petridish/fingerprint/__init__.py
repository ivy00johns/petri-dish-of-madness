"""Fingerprint — the versioned, deterministic feature-extraction layer over the
event-sourced run.sqlite (EM-314 keystone).

This package is the "build the layer once" home flagged at intake for the
model-lab instruments (#16 Babel Matrix, #21 Epoch Seismograph, #5 Fingerprint
Ticker). It holds ZERO-LLM, side-effect-free projections of the append-only
event log — pure functions of a list of EventRow dicts (the shape returned by
``SQLiteRepository.get_events``). Nothing here writes to the sim, touches the
replay surface, or calls a model: every instrument reads history and returns a
JSON-ready summary, so it stays strictly OFF the byte-identity surface.

`FEATURE_VERSION` (EM-313) versions the stylometry feature extraction: bump it
whenever the feature math changes so retro-scores across releases stay
comparable/auditable (the #1 risk called out in the source design). The whole
pipeline is a pure function of the event log + FEATURE_VERSION, so it is
replay-safe / seeded-by-construction.

Currently shipped:
  • ``resolve_agent_models`` — agent_id → per-agent model identity (shared).
  • ``build_babel_matrix``  — EM-314 dyadic (actor-model × target-model) matrix.
  • EM-313 Fingerprint Ticker — behavioral stylometry classifier (``.classifier``).
"""
from __future__ import annotations

from .classifier import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    build_centroids,
    classify,
    compute_run_fingerprints,
    features_from_turns,
    turns_from_events,
)
from .features import resolve_agent_models
from .dyadic import BABEL_MATRIX_VERSION, OUTCOME_SPECS, build_babel_matrix

__all__ = [
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "build_centroids",
    "classify",
    "compute_run_fingerprints",
    "features_from_turns",
    "turns_from_events",
    "resolve_agent_models",
    "build_babel_matrix",
    "BABEL_MATRIX_VERSION",
    "OUTCOME_SPECS",
]
