"""W8 / EM-064 — the chaos layer: LLM-driven animals (actor_type "animal").

Animals are a DISTINCT actor type from human agents: own persona (role cards),
own (looser, under-constrained) action set, own slow cadence, own logging
channel. They act mostly via a zero-LLM weighted reflex and only occasionally via
a cheap, intentionally under-constrained LLM decision — that occasional decision
is where the chaos ("the LLM decided the cat should commit arson") comes from.

The runtime is free-scale by construction: a reflex tick makes ZERO router calls,
an acted tick makes AT MOST ONE, and an unavailable model_profile falls back to
reflex-only (never crashing the loop, never escalating to a paid profile).
"""
from .runtime import AnimalRuntime

__all__ = ["AnimalRuntime"]
