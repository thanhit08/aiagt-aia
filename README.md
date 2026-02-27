# AIA (AI Agent Toolkit)

## Local setup
1. Create env file:
```bash
cp .env.example .env
```
2. For real services, set:
- `AIA_USE_REAL_SERVICES=true`
- OpenAI/Jira/Telegram credentials in `.env`
3. Install and run:
```bash
pip install -e .
uvicorn aia.api.main:app --host 0.0.0.0 --port 8000
```

## Docker Compose (recommended)
`docker-compose.yml` already links `.env` using `env_file`.

1. Ensure `.env` exists.
2. For compose, set:
- `QDRANT_URL=http://qdrant:6333`
- `REDIS_ENABLED=true`
- `REDIS_URL=redis://redis:6379/0`
- `MONGO_ENABLED=true`
- `MONGO_URL=mongodb://mongo:27017`
3. Start everything:
```bash
docker compose up --build
```
4. Stop:
```bash
docker compose down
```

## Qdrant local docker only (without compose)
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
    "conversation_id":"optional-conv-id",
    "instruction":"Find issues assigned to me in Jira and send summary to Telegram",
    "issues":[]
  }'
```

## Real credentials required
- OpenAI: `OPENAI_API_KEY`
- Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- Telegram: `TELEGRAM_BOT_TOKEN` (+ optional `TELEGRAM_DEFAULT_CHAT_ID`)

## Telegram bot setup
1. Create bot with `@BotFather` and copy token.
2. Send at least one message to your bot from Telegram app.
3. Get chat id via Bot API:
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates"
```
4. Put chat id into `.env` as `TELEGRAM_DEFAULT_CHAT_ID`.

## Slack status
- Slack actions currently return: `not supported yet`.
- Response includes suggestion to use Telegram action `telegram_send_message`.

## Redis usage
- Response cache for repeated requests (`REDIS_RESPONSE_TTL_SECONDS`).
- Per-user rate limiting (`REDIS_RATE_LIMIT_PER_MINUTE`).
- Safe fallback to in-memory cache when Redis is unavailable.

## MongoDB conversation memory
- Stores conversations, user/assistant messages, and tools used per message.
- Stores raw request/response logs for audit.
- Context algorithm: rolling summary + recent window.
- Tune with:
  - `CONTEXT_RECENT_MESSAGES`
  - `CONTEXT_MAX_MESSAGES`

## CI/CD
- CI: `.github/workflows/ci.yml`
- CD: `.github/workflows/cd.yml`
- Optional Render auto-deploy via `RENDER_DEPLOY_HOOK_URL`
