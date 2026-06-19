# Contract — EM-222 relevance-scored memory retrieval

Integration boundaries for the parallel build. Agents implement against THESE signatures
exactly. Two ownership lanes (no shared files):

- **Lane A — infra (providers + persistence):** `providers/{base,adapters,mock,router}.py`,
  `config/profiles.yaml`, `persistence/repository.py`.
- **Lane B — retriever + integration:** NEW `agents/memory_retrieval.py`,
  `agents/runtime.py`, `config/loader.py`.

Lane B builds against the signatures below; the wave gate validates integration.

## 1. Embedding seam (Lane A)

**`providers/base.py`** — add to the `Provider` Protocol:
```python
async def embed(self, texts: list[str]) -> list[list[float]]:
    """One vector per input text (same order). Raises ProviderError on failure."""
```

**`providers/adapters.py`** — `OpenAICompatibleAdapter.embed`:
- `POST {self._base_url}/embeddings`, headers as in `chat` (Bearer if api_key), body
  `{"model": self._model_id, "input": texts}`.
- Parse `data["data"][i]["embedding"]` → `list[list[float]]` ordered by `data[i].index`.
- Reuse the existing httpx client + `ProviderError` semantics. No decision-cache.

**`providers/mock.py`** — `MockProvider.embed`:
- Deterministic, no network. For each text produce a fixed-dim vector (default **1024**):
  hash tokens → bucket accumulation → **L2-normalize**. Same text ⇒ identical vector;
  related texts (shared tokens) ⇒ higher cosine. Add `embed_dim: int = 1024` ctor arg.

**`providers/router.py`** — `Router.embed`:
```python
async def embed(self, texts: list[str]) -> list[list[float]]:
    """Route to the dedicated embed adapter (the 'embed' profile). Raises if no embed
    profile configured. NOT decision-cached."""
```
- Build an embed adapter at init from the profile named **`embed`** (if present). Expose
  `Router.has_embeddings -> bool`. If absent, `embed()` raises a clear error (caller falls back).
- In tests, the embed adapter is the injected MockProvider (via `adapter_overrides`).

**`config/profiles.yaml`** — add an `embed` profile:
```yaml
  - name: embed
    adapter: openai-compatible
    model_id: bge-m3            # gating resolved 2026-06-19; gemini-embedding-001 = 3072-dim alt
    base_url: http://localhost:3001/v1
    api_key_env: FREELLMAPI_KEY
    color: "#9b59b6"
```

## 2. Persistence (Lane A) — `persistence/repository.py`

Schema (additive migration; `CREATE TABLE IF NOT EXISTS`):
```sql
CREATE TABLE IF NOT EXISTS event_embeddings (
  seq   INTEGER PRIMARY KEY REFERENCES events(seq) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dim   INTEGER NOT NULL,
  vec   BLOB NOT NULL            -- little-endian float32 * dim
);
```
Methods:
```python
def get_event_embeddings(self, run_id: int, seqs: list[int]) -> dict[int, list[float]]:
    """seq -> vector, for the subset that has a cached embedding."""

def put_event_embeddings(self, rows: list[tuple[int, str, int, list[float]]]) -> None:
    """(seq, model, dim, vec) → upsert; pack vec as little-endian float32 BLOB."""

def fetch_memory_candidates(
    self, run_id: int, agent_id: str, broadcast_kinds: tuple[str, ...], limit: int
) -> list[dict]:
    """Newest-first candidate corpus: events WHERE run_id=? AND
       (actor_id=? OR target_id=? OR kind IN broadcast_kinds) ORDER BY seq DESC LIMIT ?.
       Each dict: {seq, tick, kind, text}. (text may be ''.)"""
```
Pack/unpack with `struct`/`array` (`'f'`). `run_id` is the active run.

## 3. Retriever (Lane B) — NEW `agents/memory_retrieval.py` (pure, GL/IO-free)

```python
BROADCAST_KINDS: tuple[str, ...]  # rule_passed/rejected/proposed, random_event,
                                  # world_extinct, god_miracle, name_town, ... (global-salience)

def cosine(a: list[float], b: list[float]) -> float: ...        # 0 if either is zero-norm

def build_query_text(agent, world, recent_events: list[dict]) -> str:
    """'what's on the agent's mind': location + top need + last ~3 perceived event texts."""

@dataclass
class RetrievalWeights:
    relevance: float; importance: float; recency: float; recency_halflife_ticks: int

def score_candidates(
    query_vec: list[float],
    candidates: list[dict],                 # {seq, tick, kind, text}
    embeddings: dict[int, list[float]],     # seq -> vec (must cover candidates)
    now_tick: int,
    weights: RetrievalWeights,
    importance_of,                          # callable(event_dict)->float (pass _event_importance)
) -> list[dict]:
    """Return candidates sorted DESC by
       w.relevance*norm(cosine) + w.importance*norm(importance) + w.recency*decay(now-tick).
       Each component normalized to [0,1] across the candidate set; recency = 0.5**((now-tick)/halflife).
       Stable tie-break by seq DESC. Pure + deterministic."""
```

## 4. Config (Lane B) — `config/loader.py`

`WorldParams.memory_retrieval` (nested dataclass + yaml parse + embedded-default mirror):
```python
@dataclass
class MemoryRetrievalParams:
    enabled: bool = True
    embed_model: str = "bge-m3"
    top_k: int = 12
    recent_tail: int = 6
    candidate_limit: int = 400
    w_relevance: float = 0.5
    w_importance: float = 0.3
    w_recency: float = 0.2
    recency_halflife_ticks: int = 200
```
Parsed from `world.yaml` `memory_retrieval:` (absent ⇒ defaults). Add to both shipped yamls.

## 5. Integration (Lane B) — `agents/runtime.py`

```python
async def _retrieve_memory(self, agent, world, recent_events: list[dict]) -> list[dict]:
    """The memory event list _assemble_context renders.
       - background tier OR not params.memory_retrieval.enabled OR not router.has_embeddings
         → return recent_events[-_effective_memory_window(agent, params):]   (UNCHANGED today)
       - else: query→embed; fetch_memory_candidates; ensure embeddings (get cached, embed
         miss, put); score_candidates; top_k; merge with recent_events[-recent_tail:];
         dedupe by seq; order by tick ascending; return.
       - on ANY exception (embed/DB) → blind-recency fallback (logged once, degraded)."""
```
- `run_turn` (and the reflex fallback path) call `await self._retrieve_memory(...)` and pass
  the result into `_assemble_context` as the memory list.
- `_assemble_context` renders the **passed** memory list as the memory block (the retriever
  owns bounding; do not re-slice it away). Background path is byte-identical to today.
- The repo handle + active `run_id` are reachable from the runtime/loop (see TickLoop wiring).

## Invariants (verify pass checks these)

- Background-tier prompt rendering is **byte-identical to pre-EM-222** (diet untouched).
- A turn **never raises** out of `_retrieve_memory`; embeddings down ⇒ blind recency.
- Embeddings are written **once per event** (seq cache hit on the second turn).
- Scoring is **pure + deterministic** (same inputs ⇒ same order).
- No decision-cache on the embed path; embeddings ADD calls (north-star).
- `event_embeddings` is **not** in the world snapshot (EM-155 byte-equality unaffected).
