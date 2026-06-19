# EM-222 — Relevance-scored long-term memory retrieval (design)

> Status: approved 2026-06-19 ("go"). Spike → first build. Source research:
> `docs/research/smallville-to-sid-2026-06-18.md`. Integration interfaces:
> `contracts/em222-memory-retrieval.md`.

## Goal

Protagonist/supporting agents recall **relevant** old events, not just the last ~12.
Today memory is a pure recency window (`_effective_memory_window`, in-memory `_memory`
buffer). Add Smallville-style **recency × importance × relevance** retrieval over the
**persisted event log**, using FreeLLMAPI embeddings (`bge-m3`, 1024-dim — gating question
resolved 2026-06-19, EM-222 ledger row). North-star-aligned: it **adds** calls (embeddings),
never caches-to-mute; the decision cache stays OFF.

## Decisions (locked)

- **Store:** SQLite event-log retrieval over full run history (survives restart), with a
  cached `event_embeddings` table. (Chosen over the simpler in-memory expanded buffer.)
- **Scope:** protagonist + supporting tiers only. **Background tier keeps its blind-recency
  prompt diet (EM-161) unchanged.**
- **Candidate corpus (v1):** an agent's *autobiographical + globally-salient* memory —
  events where `actor_id == agent OR target_id == agent OR kind IN broadcast_kinds`
  (reflections ride in as the agent's own actor events). Exact co-location-at-the-time
  witnessing is a **v2 refinement** (the in-memory buffer had it; SQLite trades it for
  full-history depth).
- **Default:** `memory_retrieval.enabled = true`.

## Architecture — five isolated units

1. **Embedding seam (providers).** `Provider.embed(texts) -> list[vec]`; implemented on
   `OpenAICompatibleAdapter` (`POST {base_url}/embeddings`), `MockProvider` (deterministic,
   no network), and `Router.embed()` routed to a dedicated **`embed` profile** (model
   `bge-m3`, proxy base_url, `FREELLMAPI_KEY`) — embeddings use this fixed model, not the
   agent's chat profile.
2. **Embedding store (SQLite).** `event_embeddings(seq PK → events.seq, model, dim, vec BLOB)`
   — one float32-packed vector per event, embedded once and reused. Orthogonal to the world
   snapshot ⇒ no EM-155 byte-equality impact. Repo: `get_event_embeddings`,
   `put_event_embeddings`, `fetch_memory_candidates`.
3. **Retriever (pure scoring + async orchestration).** New module
   `backend/petridish/agents/memory_retrieval.py`: pure `score_candidates` (cosine ×
   importance × recency, each normalized to [0,1], tie-break by `seq`) + `build_query_text`.
   The runtime orchestration embeds the query, fetches candidates, ensures embeddings (cache
   miss → embed + persist), scores, takes top-K, merges with a small recent tail.
4. **Integration + safety.** `AgentRuntime._retrieve_memory()` returns the memory event list
   `_assemble_context` renders: protagonist/supporting → merged retrieval; **background →
   unchanged blind recency**. Config `world.params.memory_retrieval`. **Any embed/DB failure
   → graceful fallback to blind recency for that turn** (never crash/block a turn).
5. **Tests.** Mock embed path; scoring (an old high-relevance event outranks a recent
   low-relevance one); determinism (same inputs → same top-K); fallback on embed failure;
   background tier untouched; embed-once caching; a live proxy smoke test (skipped if `:3001`
   unreachable).

## Data flow (protagonist/supporting turn)

```
run_turn → _retrieve_memory(agent, world, recent_events):
  if background or not enabled: return recent_events[-window:]          # unchanged
  query = build_query_text(agent, world, recent_events)                 # location+need+last~3
  qvec  = await router.embed([query])[0]
  cands = repo.fetch_memory_candidates(run_id, agent.id, BROADCAST_KINDS, candidate_limit)
  have  = repo.get_event_embeddings(run_id, [c.seq for c in cands])
  miss  = [c for c in cands if c.seq not in have]
  if miss: vecs = await router.embed([c.text for c in miss]); repo.put_event_embeddings(...)
  scored = score_candidates(qvec, cands, embeddings, now_tick, weights) # cosine×imp×rec
  topk   = scored[:top_k]
  return dedup_by_seq(recent_events[-recent_tail:] + topk) ordered by tick
  # on ANY embed/DB exception → return recent_events[-window:] (logged degraded)
```

## Out of scope (v1)

Exact co-location-history witnessing; reflection-summary rollups; cross-run memory; embedding
re-indexing on model change; background-tier retrieval. All notable as follow-ups.

## Definition of done

Backend suite green (existing 922 + new EM-222 tests); the retrieval path proven against the
MockProvider deterministically; live proxy smoke test passes when `:3001` is up; graceful
fallback verified; background-tier prompt byte-behavior unchanged; ledger EM-222 → done.
