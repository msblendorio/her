#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example and set OPENAI_API_KEY first." >&2
  exit 1
fi

# shellcheck disable=SC1091
[ -d .venv ] && source .venv/bin/activate

exec python -m her.main
