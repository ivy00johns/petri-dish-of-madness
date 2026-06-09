# Contract: Provider Router & Config — v1.0.0

The model-routing layer. The marquee feature ("flexible model control") lives here.

## Provider interface

```python
class Provider(Protocol):
    name: str          # profile name
    color: str         # hex, for UI color-coding
    async def chat(self, messages: list[dict], *, max_tokens: int, temperature: float) -> str:
        """Return the assistant message text. Raises ProviderError on transport/HTTP failure.
        messages: OpenAI-style [{role: system|user|assistant, content: str}, ...]."""
```

`ProviderError` carries `.profile`, `.status`, `.detail`. The agent runtime treats a
ProviderError as a failed turn (logged as `parse_failure` kind with reason="provider_error",
agent falls back to idle) — it must NOT crash the loop.

## Router

```python
class Router:
    def __init__(self, profiles: list[ModelProfile]): ...
    def reassign(self, agent_id: str, profile_name: str) -> None  # validates profile exists
    def profile_for(self, agent_id: str) -> ModelProfile
    async def chat(self, profile_name: str, messages, *, max_tokens, temperature) -> str
    async def health(self, profile_name: str) -> bool   # cheap availability probe (used by /api/profiles.available)
    def legend(self) -> list[dict]   # [{name, adapter, model_id, color, available}]
```

## Adapters (all implement Provider)

| adapter | how it calls | covers |
|---------|--------------|--------|
| `openai` | POST `{base_url}/chat/completions`, `Authorization: Bearer {key}`, body `{model, messages, max_tokens, temperature}`, read `choices[0].message.content` | **FreeLLMAPI**, Ollama (`/v1`), vLLM, Groq, LM Studio, OpenRouter, Together |
| `anthropic` | Messages API `/v1/messages`, `x-api-key`, system split out, read `content[0].text` | Claude |
| `gemini` | `generateContent`, map roles, read `candidates[0].content.parts[0].text` | Gemini |
| `mock` | returns scripted JSON actions from a list/generator; no network | tests + offline dev |

All adapters: timeout default 30s, 1 network retry on 5xx/429 with small backoff, then raise ProviderError.

## Usage capture — W6 / EM-067

`chat()` STILL returns `str` (no breaking change). Usage rides alongside as adapter state:

```python
class Provider(Protocol):
    last_routed_via: str | None   # W4 — model that actually answered
    last_usage: dict | None       # W6 — set after a successful chat(); None for Mock / on error
# last_usage shape (null-tolerant — Gemini free tier often omits tokens):
# { "input_tokens": int|None, "output_tokens": int|None,
#   "latency_ms": float, "finish_reason": str|None, "cached": bool }
class Router:
    def last_usage(self, profile_name: str) -> dict | None   # mirrors last_routed_via
```

- **openai** adapter reads `usage.prompt_tokens`/`completion_tokens` + `choices[0].finish_reason`;
  **anthropic** reads `usage.input_tokens`/`output_tokens` + `stop_reason`; **gemini** reads
  `usageMetadata.promptTokenCount`/`candidatesTokenCount` (may be absent → null). Measure
  `latency_ms` with a `perf_counter` wrapper around the whole `_post_with_retry`.
- The runtime injects these into the `llm_call` event payload under the OTel keys
  (`gen_ai.usage.input_tokens`/`output_tokens`, `latency_ms`, `gen_ai.response.finish_reasons`),
  replacing the W5 nulls. **Per-attempt `llm_call` rows**: on a parse-failure retry, emit one
  `llm_call` per attempt (attempt 1 + 2), each with its own usage, sharing the turn_id.
- **Per-provider RPD/TPD** is computed from `llm_call` rows by `get_analytics().usage`
  (no separate table). **Cap-aware throttling** is policy in the tick loop (config
  `world.usage_caps`), NOT inside `chat()` — when a provider nears a cap, slow ticks / prefer a
  cheaper profile; never block `chat()`. Mock has no usage (`last_usage=None`).

## ModelProfile (config)

```yaml
# config/profiles.yaml
profiles:
  - name: groq-llama          # unique; referenced by agents + reassign API
    adapter: openai           # openai|anthropic|gemini|mock
    base_url: ${FREELLMAPI_BASE_URL:-http://localhost:3001/v1}
    api_key_env: FREELLMAPI_KEY      # env var holding the bearer token (NOT the literal key)
    model_id: llama-3.3-70b-versatile
    max_tokens: 512
    temperature: 0.8
    color: "#e74c3c"
```
Rules: `api_key_env` names an env var (never store secrets in YAML). `${VAR:-default}`
interpolation supported for `base_url`/`model_id`. A profile whose env var is unset and
adapter != mock is loaded but reports `available=false`.

## world.yaml

```yaml
# config/world.yaml
world:
  agent_count: 5                 # used if `agents:` not fully specified
  tick_interval_seconds: 3
  turns_per_day: 20
  energy_decay_per_turn: 4
  death_after_zero_turns: 5
  starting_energy: 100
  starting_credits: 10
  recharge_cost: 2
  recharge_amount: 30
  work_reward: 4
  forage_reward: 1
  steal_max: 8
  ubi_amount: 2
  memory_window: 12
  attack_energy_cost: 6
places:
  - { id: plaza,    name: Central Plaza, x: 500, y: 500, kind: social,     description: "Open square where everyone mingles." }
  - { id: market,   name: Market,        x: 750, y: 400, kind: work,       description: "Earn credits by working." }
  - { id: townhall, name: Town Hall,     x: 250, y: 350, kind: governance, description: "Propose and vote on rules." }
  - { id: commons,  name: The Commons,   x: 500, y: 750, kind: wild,       description: "Forage for scraps." }
  - { id: home,     name: Hearth,        x: 300, y: 650, kind: home,       description: "Rest and recharge." }
agents:                          # seed agents; profile must match a profiles[].name
  - { name: Ada,   personality: "Pragmatic engineer; values fairness, distrusts freeloaders.", profile: groq-llama,  location: plaza }
  - { name: Bram,  personality: "Charismatic opportunist; will steal if it pays.",            profile: gemini-flash, location: market }
  - { name: Cleo,  personality: "Idealistic organizer; loves rules and town halls.",          profile: groq-llama,  location: townhall }
  - { name: Dov,   personality: "Quiet survivor; hoards credits, avoids conflict.",           profile: gemini-flash, location: home }
  - { name: Esi,   personality: "Generous connector; builds alliances, shares freely.",       profile: groq-llama,  location: commons }
```
The two seed profiles (`groq-llama`, `gemini-flash`) intentionally differ → satisfies the
goal of ≥2 models in one world. Both routed through FreeLLMAPI by default.
