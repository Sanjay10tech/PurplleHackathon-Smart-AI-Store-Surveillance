# Final Submission Checklist — Purple Challenge

Complete every step before submitting. Tick boxes in order.

**Automated gate:** `python scripts/validate_submission.py` must report **10/10 checks passed**.

---

## 1. Prerequisites

- [ ] Docker Desktop / Docker Engine + Compose v2 installed
- [ ] Python 3.11+ installed
- [ ] Git clone of this repository
- [ ] CCTV sample videos placed in `data/videos/` (see step 2)

---

## 2. Dataset setup (manual — required)

Videos are **not committed** (~680 MB). From the challenge CCTV folder:

```bash
python scripts/setup_videos.py --source "/path/to/CCTV Footage"
python scripts/setup_videos.py --check
```

Expected files:

- [ ] `data/videos/CAM 1.mp4`
- [ ] `data/videos/CAM 2.mp4`
- [ ] `data/videos/CAM 3.mp4`
- [ ] `data/videos/CAM 4.mp4`
- [ ] `data/videos/CAM 5.mp4`

---

## 3. Docker stack (clean clone)

```bash
docker compose down -v          # optional: wipe DB
docker compose up --build -d
docker compose ps               # api + postgres healthy
```

- [ ] Postgres container **healthy**
- [ ] API container **healthy** on port 8000
- [ ] http://localhost:8000/docs loads

Fresh boot health (before pipeline):

- [ ] `GET /health` → `status=degraded`, `checks.database=up`, `checks.feed=unknown`
- [ ] `GET /health/ready` → `status=ready`

---

## 4. Python environment

```bash
pip install -e ".[dev]"
pip install -r pipeline/requirements.txt
```

- [ ] `pytest --version` works
- [ ] `python -c "import cv2"` succeeds

Set DB URL for pipeline scripts (host → Docker Postgres):

```bash
# Linux/macOS
export DATABASE_URL=postgresql+asyncpg://si:si@localhost:5432/store_intelligence

# Windows PowerShell
$env:DATABASE_URL="postgresql+asyncpg://si:si@localhost:5432/store_intelligence"
```

---

## 5. Tests & coverage

```bash
pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q
```

- [ ] **268 tests passed**
- [ ] Coverage **≥ 96%** on `app/` (branch-aware; currently **96.6%**)
- [ ] All `tests/**/test_*.py` files contain `# PROMPT:` attribution block

---

## 6. Full submission validation (single command)

```bash
python scripts/validate_submission.py
```

Must pass all checks:

| # | Check | Expected |
|---|-------|----------|
| 1 | data/videos present | 5 MP4 files |
| 2 | GET /health | 200, database up |
| 3 | GET /health/ready | 200, ready |
| 4 | pipeline ingest | CAM 3 + CAM 1 + CAM 5 mock over real MP4s, accepted > 0, rejected = 0 |
| 5 | project demo metrics | ≥ 1 footfall bucket written |
| 6 | GET /metrics | `series` non-empty, `meta.source=store_metrics` |
| 7 | GET /funnel | ENTRY count > 0 |
| 8 | GET /heatmap | zones length > 0 |
| 9 | GET /anomalies | 200 JSON |
| 10 | GET /health after ingest | `status=ok`, `feed=fresh` |

- [ ] **10/10 checks passed**

---

## 7. Manual pipeline verification (optional YOLO)

Mock mode (default for submission):

```bash
python -m pipeline.run --mock --ingest --persist-sessions --camera "CAM 3" --max-frames 50
```

Real YOLO (requires GPU/CPU time + downloads `yolo11n.pt`):

```bash
python -m pipeline.run --camera "CAM 3" --max-frames 30 --ingest --persist-sessions
python scripts/project_demo_metrics.py
```

- [ ] Events written to `data/pipeline/events.jsonl`
- [ ] `vision.zone.entered` events present in JSONL
- [ ] API ingest returns `accepted` > 0

---

## 8. Documentation deliverables

- [ ] [README.md](./README.md) — quick start, pipeline, validation commands
- [ ] [DESIGN.md](./DESIGN.md) — architecture, AI-Assisted Decisions
- [ ] [CHOICES.md](./CHOICES.md) — three engineering decisions
- [ ] [FINAL_GAP_ANALYSIS.md](./FINAL_GAP_ANALYSIS.md) — this audit
- [ ] [FINAL_SUBMISSION_CHECKLIST.md](./FINAL_SUBMISSION_CHECKLIST.md) — this file
- [ ] [docs/bi_validation_report.md](./docs/bi_validation_report.md) — BI test evidence
- [ ] [docs/architecture/README.md](./docs/architecture/README.md) — implemented vs planned banner

---

## 9. Submission artifacts to attach

- [ ] Repository URL or zip
- [ ] Screenshot/log: `docker compose ps` (both healthy)
- [ ] Screenshot/log: `python scripts/validate_submission.py` → 10/10
- [ ] Screenshot/log: `pytest` summary (**268 passed**, **96.6%** coverage)
- [ ] Note: reviewer must run `setup_videos.py` if videos not bundled

---

## 10. Known limitations (disclose to reviewers)

Do **not** claim these are implemented:

- Redis Streams / event bus
- WebSocket real-time push
- API authentication
- Camera CRUD endpoints from architecture contract
- Automatic metrics projection (use `scripts/project_demo_metrics.py` after ingest)
- Pipeline inside Docker image (runs on host)

---

## Quick reference — demo store

| Item | Value |
|------|-------|
| Store ID | `00000000-0000-0000-0000-000000000101` |
| Tenant ID | `00000000-0000-0000-0000-000000000001` |
| API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |

---

## Sign-off

| Role | Name | Date | validate_submission | pytest |
|------|------|------|---------------------|--------|
| Engineer | | | ☐ 10/10 | ☐ 268 pass |
| Reviewer | | | ☐ | ☐ |
