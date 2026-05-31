# Database Indexing Strategy

Indexing decisions for the core analytics tables (`events`, `sessions`, `transactions`, `anomalies`, `store_metrics`).

## Design Principles

1. **Match query paths** — indexes align to repository methods and API filters, not hypothetical joins.
2. **Composite leading columns** — `(store_id, …)` prefix enables partition pruning per store (multi-tenant retail).
3. **Partial indexes** — unique constraints and filters that exclude NULLs reduce index size and enforce idempotency without blocking multiple NULLs.
4. **Write amplification tradeoff** — append-heavy `events` gets fewer indexes than read-heavy `store_metrics`.

---

## `events`

| Index | Columns | Type | Rationale |
|-------|---------|------|-----------|
| `uq_events_idempotency_key` | `idempotency_key` | Partial UNIQUE (`WHERE idempotency_key IS NOT NULL`) | **Idempotent ingestion** — duplicate POSTs return existing row; NULL keys allowed for legacy producers |
| `ix_events_store_occurred` | `store_id`, `occurred_at` | B-tree | Primary time-range scan for store audit and analytics backfill |
| `ix_events_store_type_occurred` | `store_id`, `event_type`, `occurred_at` | B-tree | Filtered queries (`vision.*` only) without scanning unrelated event types |
| `ix_events_tenant_occurred` | `tenant_id`, `occurred_at` | B-tree | Cross-store tenant audit (admin tooling) |
| `ix_events_correlation_id` | `correlation_id` | B-tree | Distributed trace lookup; low cardinality acceptable for ops/debug volume |
| `ix_events_session_id` | `session_id` | B-tree | Join path events → session replay |

**Tradeoff:** No index on `payload` JSONB. Filtering by payload fields would require GIN (`jsonb_path_ops`) — deferred until query patterns are known post-dataset. Hot analytics reads use `store_metrics`, not raw events.

**FK:** `store_id → stores.id` (CASCADE), `session_id → sessions.id` (SET NULL) — orphaned events survive session cleanup.

---

## `sessions`

| Index | Columns | Rationale |
|-------|---------|-----------|
| `ix_sessions_store_started` | `store_id`, `started_at` | List sessions in time window |
| `ix_sessions_store_status` | `store_id`, `status` | Active session counts per store |
| `ix_sessions_store_external_track` | `store_id`, `external_track_id` | ByteTrack ID → session lookup (dedup track lifecycle) |

**Tradeoff:** No partial index on `status = 'active'` yet — added when active-session polling becomes hot path. Current composite `(store_id, status)` sufficient at MVP volume.

---

## `transactions`

| Index | Columns | Type | Rationale |
|-------|---------|------|-----------|
| `ix_transactions_store_occurred` | `store_id`, `occurred_at` | B-tree | Revenue time-series |
| `ix_transactions_session_id` | `session_id` | B-tree | Funnel: session → conversion |
| `uq_transactions_store_external_ref` | `store_id`, `external_ref` | Partial UNIQUE | **POS idempotency** — replay-safe ingestion from external systems |

**Tradeoff:** `amount` not indexed — aggregation runs on `store_metrics` rollups, not ad-hoc SUM on raw transactions at scale.

---

## `anomalies`

| Index | Columns | Type | Rationale |
|-------|---------|------|-----------|
| `ix_anomalies_store_detected` | `store_id`, `detected_at` | B-tree | API `GET /stores/{id}/anomalies` default sort |
| `ix_anomalies_store_severity_detected` | `store_id`, `severity`, `detected_at` | B-tree | Alert dashboard filtered by severity |
| `ix_anomalies_store_type_detected` | `store_id`, `anomaly_type`, `detected_at` | B-tree | Rule-specific drill-down |
| `ix_anomalies_store_open` | `store_id`, `detected_at` | Partial (`resolved_at IS NULL`) | Open-alerts widget without full table scan |

**Tradeoff:** Partial open-anomaly index duplicates some rows with `ix_anomalies_store_detected` — acceptable; open-alert queries are frequent and smaller result sets justify dedicated index.

---

## `store_metrics`

| Index | Columns | Type | Rationale |
|-------|---------|------|-----------|
| `uq_store_metrics_bucket` | `store_id`, `metric_name`, `bucket_start`, `granularity`, `dimensions` | UNIQUE | **Idempotent upsert** — analytics worker retries safe |
| `ix_store_metrics_store_metric_bucket` | `store_id`, `metric_name`, `bucket_start` | B-tree | `GET /stores/{id}/metrics` range query |

**Tradeoff:** JSONB `dimensions` in UNIQUE constraint — equality match on full JSON document. Requires consistent key ordering in application layer when building dimensions dicts. Alternative (hash column) adds complexity; chosen for debuggability.

---

## Idempotency Summary

| Table | Mechanism | Repository method |
|-------|-----------|---------------------|
| `events` | Partial unique `idempotency_key` + pre-check | `EventRepository.create_idempotent()` |
| `transactions` | Partial unique `(store_id, external_ref)` | `TransactionRepository.create_idempotent()` |
| `store_metrics` | Unique bucket constraint + UPSERT | `StoreMetricRepository.upsert()` |

All three use `begin_nested()` savepoints on conflict to avoid rolling back the entire request transaction.

---

## Performance at Scale

| Volume trigger | Recommended action |
|----------------|-------------------|
| >10M events/month | TimescaleDB hypertable on `events.occurred_at`; drop `ix_events_tenant_occurred` if unused |
| >1M open anomalies | Partition `anomalies` by `detected_at` monthly |
| JSONB payload queries | Add GIN index on `events.payload` with targeted `jsonb_path_ops` |
| Cross-store metrics | BRIN on `store_metrics.bucket_start` if table >> RAM |

---

## Migration

Apply with:

```bash
alembic upgrade head
```

Revision chain: `001` (tenants, stores, legacy) → `002` (core analytics tables).
