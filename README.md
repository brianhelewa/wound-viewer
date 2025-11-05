# Wound Viewer + Notes (Claude)

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt

cp .env.example .env
# edit .env with your ANTHROPIC_API_KEY and model

# Terminal 1: API
./scripts/dev-api.sh

# Terminal 2: Web
./scripts/dev-web.sh
# then open: http://localhost:8000/index.html
