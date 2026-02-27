# AIA (Accuracy Intelligence Agent)

## Local Run
```bash
pip install -e .
uvicorn aia.api.main:app --host 0.0.0.0 --port 8000
```

Health check:
```bash
curl http://localhost:8000/health
```

QA intake with CSV:
```bash
curl -X POST http://localhost:8000/qa-intake \
  -H "Content-Type: application/json" \
  -d '{
    "user_id":"test-user",
    "instruction":"Find accuracy issues and route to Slack and Jira",
    "issues":[
      {
        "issue_id":"1",
        "title":"Wrong total amount",
        "description":"Output differs from expected value",
        "steps":"Run checkout flow",
        "severity":"critical"
      }
    ]
  }'
```

Optional file upload endpoint (when `python-multipart` is installed):
```bash
curl -X POST http://localhost:8000/qa-intake-upload \
  -F "user_id=test-user" \
  -F "instruction=Find accuracy issues and route to Slack and Jira" \
  -F "file=@issues.csv;type=text/csv"
```

## CI/CD
- CI: `.github/workflows/ci.yml` runs compile + tests on PR/push.
- CD: `.github/workflows/cd.yml` builds/pushes Docker image to GHCR on `main`.
- Optional deploy: set `RENDER_DEPLOY_HOOK_URL` secret to auto-deploy and get a live endpoint.

## Required Secrets (for live deploy)
- `RENDER_DEPLOY_HOOK_URL` (optional): Render service deploy hook URL.
