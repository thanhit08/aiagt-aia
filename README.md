# AIA (AI Agent Toolkit)

## Local setup
1. Create env file:
```bash
cp .env.example .env
```
2. For real services, set:
- `AIA_USE_REAL_SERVICES=true`
- OpenAI/Jira/Slack credentials in `.env`
3. Install and run:
```bash
pip install -e .
uvicorn aia.api.main:app --host 0.0.0.0 --port 8000
```

## Qdrant local docker (no API key)
```bash
docker run -p 6333:6333 qdrant/qdrant
```

## Endpoints
- `GET /health`
- `POST /qa-intake` (JSON)
- `POST /qa-intake-upload` (multipart; requires `python-multipart`)

## curl test (JSON)
```bash
curl -X POST http://localhost:8000/qa-intake \
  -H "Content-Type: application/json" \
  -d '{
    "user_id":"test-user",
    "instruction":"Find issues assigned to me in Jira and post summary to Slack",
    "issues":[]
  }'
```

## Real credentials required
- OpenAI: `OPENAI_API_KEY`
- Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- Slack: `SLACK_BOT_TOKEN`

## CI/CD
- CI: `.github/workflows/ci.yml`
- CD: `.github/workflows/cd.yml`
- Optional Render auto-deploy via `RENDER_DEPLOY_HOOK_URL`

