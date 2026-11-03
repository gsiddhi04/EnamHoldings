#!/usr/bin/env bash
# One command: install, refresh data, build the frontend, serve.
#   ./run.sh                 everything
#   ./run.sh --no-refresh    skip the data refresh (fast restart)
#   ./run.sh --no-build      skip the frontend build
#   PORT=9000 ./run.sh       change the port (default 8000)
set -euo pipefail
cd "$(dirname "$0")"

REFRESH=1; BUILD=1
for a in "$@"; do
  case "$a" in
    --no-refresh) REFRESH=0 ;;
    --no-build) BUILD=0 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
PORT="${PORT:-8000}"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Python environment"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "Python 3.9+ is required (found $("$PY" --version))" >&2; exit 1; }
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt

if [ ! -f .env ] && [ -z "${GEMINI_API_KEY:-}${ANTHROPIC_API_KEY:-}" ]; then
  echo "No LLM key found (.env / environment). Prices, filings and the rule-based digest still work;"
  echo "results tables, summaries, research promises, bull/bear and Ask FINN need one. See .env.example."
fi

if [ "$REFRESH" = 1 ]; then
  say "Refreshing data (prices, NSE filings, classify, enrich, alerts)"
  # a flaky network must not stop the app from starting: the last good data is still served
  .venv/bin/python -m backend.refresh || echo "Refresh had problems; serving the data already on disk."
fi

if [ "$BUILD" = 1 ]; then
  if command -v npm >/dev/null 2>&1; then
    say "Building the frontend"
    (cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund --silent; } && npm run build --silent -- --logLevel warn)
  elif [ -d frontend/dist ]; then
    echo "npm not found; using the existing frontend/dist"
  else
    echo "npm (Node 18+) is needed to build the frontend, and there is no frontend/dist yet" >&2; exit 1
  fi
fi

say "Serving on port $PORT"
IP="$( (ipconfig getifaddr en0 || ipconfig getifaddr en1 || hostname -I | awk '{print $1}') 2>/dev/null || true)"
echo "  this computer: http://localhost:$PORT"
[ -n "$IP" ] && echo "  your phone (same wifi): http://$IP:$PORT"
exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
