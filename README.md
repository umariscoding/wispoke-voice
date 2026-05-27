# wispoke-voice

LiveKit Agents worker for the Wispoke voice booking platform.

## Quick start

```bash
# Install (uv-managed)
uv sync

# Configure
cp .env.example .env
# fill in LIVEKIT_*, provider keys, WISPOKE_SERVICE_JWT_SECRET

# Run the worker (dev mode = auto-reload + verbose logs)
uv run python -m wispoke_voice.worker dev
```

## Layout

```
src/wispoke_voice/
├── worker.py         # AgentServer entrypoint, job dispatch
├── config.py         # env-var settings (pydantic-settings)
├── api_client.py     # HTTPX client → wispoke-api (service JWT)
├── agent/            # BookingAgent + state machine + readback
├── tools/            # @function_tool registrations (one file per group)
├── providers/        # STT/LLM/TTS factories (per-tenant)
├── tenant/           # TenantConfig dataclass + loader
├── prompts/          # system prompt template + en/da i18n + voice catalog
└── observability/    # structured JSON logs + latency timers
```

## Architecture notes

- **Cascaded pipeline** (STT → LLM with strict tools → TTS), not speech-to-speech.
- **Tools-only booking**: the LLM cannot state availability or book unless a
  tool returns the slot. JSON-schema args; mandatory read-back; state machine
  layered over the LLM.
- **Multi-tenant**: room metadata carries `company_id`; the worker loads tenant
  config + tool bindings per session. No global state per-tenant.
- **SOLID**: providers/tools/prompts are pluggable; the agent depends on
  protocols, not concrete classes.
