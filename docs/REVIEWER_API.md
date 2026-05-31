# Reviewer API Guide

Purple Tech evaluators: use this document to call every demo endpoint with **`purple-demo-key`**.

**Live machine-readable guide:** `GET http://localhost:8000/reviewer/api` (no auth)

---

## 1. Start the stack

```bash
git clone <repository-url>
cd Smart-AI-StoreSurveillance
docker compose up --build
```

Wait until http://localhost:8000/health returns `"status": "ok"`.

---

## 2. Demo credentials

| Field | Value |
|-------|-------|
| **Store ID** | `00000000-0000-0000-0000-000000000101` |
| **API key** | `purple-demo-key` |
| **Header** | `X-API-Key: purple-demo-key` |
| **Reviewer mode** | `REVIEWER_MODE=true` (default in Docker) |

In reviewer mode, protected routes accept **`purple-demo-key`** even if `API_KEY` is set differently.

---

## 3. Public endpoints (no API key)

```bash
curl http://localhost:8000/health
curl http://localhost:8000/reviewer
curl http://localhost:8000/reviewer/api
curl http://localhost:8000/health/ready
```

| URL | Purpose |
|-----|---------|
| http://localhost:8000/dashboard/ | Live dashboard (pre-filled demo credentials) |
| http://localhost:8000/docs | Swagger UI — click **Authorize**, enter `purple-demo-key` |

---

## 4. Protected endpoints (require `X-API-Key`)

Replace `{store}` with `00000000-0000-0000-0000-000000000101`.  
**Do not** use `{id}` or `%7Bid%7D` — those return **401** or **422**.

### Metrics

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=visitor.count"
```

### Funnel

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
```

### Heatmap

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap"
```

### Anomalies

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies"
```

### Dashboard summary

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary"
```

### Retail journeys

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys"
```

### Re-ID evidence

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/reid/evidence"
```

---

## 5. Verify all links

```bash
python scripts/verify_reviewer_api_links.py
```

Writes `docs/REVIEWER_API_VERIFICATION.md` with HTTP status per URL.

---

## 6. Common errors

| Symptom | Cause | Fix |
|---------|-------|-----|
| **401 Unauthorized** | Missing or wrong API key | Add `-H "X-API-Key: purple-demo-key"` |
| **401 on `.../stores/{id}/...`** | Literal `{id}` in URL | Use full UUID `00000000-0000-0000-0000-000000000101` |
| **422 Validation Error** | `{id}` sent with API key | Same — use real store UUID |
| Empty funnel / metrics | Fresh DB, no CCTV bootstrap | Wait for entrypoint bootstrap or mount `data/videos/` |

---

## 7. Swagger / OpenAPI

1. Open http://localhost:8000/docs  
2. Click **Authorize** (top right)  
3. Enter: `purple-demo-key`  
4. Try **GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel**

---

## 8. Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `REVIEWER_MODE` | `true` | Accept demo key on protected routes |
| `API_KEY` | `purple-demo-key` | Configured key (also accepted when reviewer mode off) |
| `API_KEY_REQUIRED` | `true` | Enforce header on ingest + store analytics |
| `REVIEWER_API_BASE_URL` | `http://localhost:8000` | Base URL in `/reviewer/api` curl examples |

Disable reviewer mode for production-only keys:

```bash
REVIEWER_MODE=false API_KEY=your-production-secret docker compose up
```
