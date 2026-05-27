# wispoke-voice — LiveKit Agents worker (dials OUT to LiveKit Cloud; no inbound).
#
# A Dockerfile (not Nixpacks) so the build is fully deterministic: pinned
# Python, explicit `pip install .` of the src-layout package, and a build-time
# model download. Avoids Nixpacks' auto-injected `uv pip install -e .` (uv
# isn't on the image) and railway.json/nixpacks.toml precedence ambiguity.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# Build manifest + source must both be present before `pip install .` — the
# hatchling build reads pyproject AND packages from src/. (The deploy failure
# we saw was exactly this: only pyproject.toml was copied, so the package
# installed empty → ModuleNotFoundError.)
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# Pre-fetch the turn-detector ONNX model at build time so the first call
# doesn't stall on a cold download. worker import is side-effect-free (no
# settings validation at import), so this needs no env vars.
RUN python -m wispoke_voice.worker download-files

# Long-lived worker process. Not a web server — no EXPOSE / port needed.
CMD ["python", "-m", "wispoke_voice.worker", "start"]
