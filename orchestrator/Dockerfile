# ============================================================================
# Research Agent Swarm — Orchestrator (Python)
# ============================================================================
FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

EXPOSE 5000

CMD ["uvicorn", "orchestrator:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1"]
