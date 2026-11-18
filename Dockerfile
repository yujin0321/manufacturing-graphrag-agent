# iMAKS XAI agent server — dependencies only.
# The repository (code + restored runtime data) is bind-mounted at /app by docker-compose.yml,
# so the runtime ZIP contents never get baked into an image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY docs/agent_handoff/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --create-home --uid 1000 imaks

USER imaks
EXPOSE 8770

# Generation mode + local CSV analysis. Public host, limits and the access code come from .env (see docs/DEPLOY.md).
CMD ["python", "scripts/run_xai_agent.py", "--serve", "--allow-local-analysis", "--port", "8770", \
     "--page", "sensor-ui/integration/serve-page.html"]
