set -euo pipefail
[ -f .env ] && set -a && . ./.env && set +a
export PYTHONPATH="$PWD"
uvicorn server.notes_claude:app --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-5055}" --reload
