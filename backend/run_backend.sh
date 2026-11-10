#!/usr/bin/env bash
# Starts the DisasterOps backend on http://localhost:5001
# First run automatically seeds the real GSI Fukuoka dataset from ../data
# (falls back to the synthetic demo data if the GSI files are missing).
set -e
# Free local AI agent by default (Ollama). Override by exporting these before running,
# e.g. GROQ_API_KEY=... or ANTHROPIC_API_KEY=... (paid) -- provider is then auto-detected.
if [ -z "$LLM_PROVIDER" ] && [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$GROQ_API_KEY" ] && [ -z "$GEMINI_API_KEY" ] && [ -z "$OPENROUTER_API_KEY" ]; then
  export LLM_PROVIDER=ollama
fi
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:14b}"
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi
pip install -q -r requirements.txt
echo "Starting DisasterOps backend on http://localhost:5001 ..."
python3 -m app.main
