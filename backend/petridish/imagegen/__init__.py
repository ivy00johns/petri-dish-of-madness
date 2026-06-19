"""Wave I / EM-210 — the image-generation provider seam (The Atelier).

A tiny provider abstraction mirroring `providers/` in spirit but far simpler:
one `async fetch_png(prompt) -> bytes | None` call that NEVER raises into the
loop. The loop owns paths + ids; the provider only turns a prompt into PNG
bytes (or None on any failure). See contracts/wave-i-atelier.md §1.
"""
from .provider import ImageProvider, build_provider

__all__ = ["ImageProvider", "build_provider"]
