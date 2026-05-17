# Cloud Logging — Log Analytics + retention

Notes for when you're ready to upgrade the platform's GCP project from
default-tier Cloud Logging to SQL-queryable Log Analytics, and bump
retention beyond the 30-day default.

## Why

The Cycls agent runtime already emits structured JSON to stdout (captured
by Cloud Logging) for:

- `level: "error"` — unhandled exceptions in the SSE encoder. See [CYCLS.md](../CYCLS.md#--query-is-the-qa-mechanism).
- `level: "usage"` — per-turn token counts + cost. See [CYCLS.md](../CYCLS.md#cost-logging).

The `cycls logs` CLI runs queries via Cloud Logging's filter language and
pulls raw entries to aggregate locally. Two scale walls to anticipate:

1. **Aggregation latency.** Above ~10K usage entries in the query window,
   `cycls cost` starts pulling MB over the wire. Server-side SQL aggregation
   keeps it constant-time regardless of volume.
2. **Retention.** Default `_Default` bucket keeps 30 days. Incident retros
   and month-over-month cost trends need more.

Log Analytics is the GCP-native answer to both. It's free (queries don't
charge per-byte; storage beyond 30 days is ~$0.01/GiB/month → noise at
our volume).

## What the upgrade enables

- SQL queries on the same logs we're already emitting, via a BigQuery-style
  engine: `SELECT user_id, SUM(jsonPayload.cost) FROM ... GROUP BY user_id`.
- The Logs Explorer UI gains an "Analytics" tab with full SQL.
- Cycls CLI could later route `cycls cost` aggregations through SQL instead
  of the current pull-and-sum-in-Python path (server-side scale).
- 90-day (or longer) retention for QA error reference IDs and cost trends.

## Pulumi resource

Add to the stack that owns the agent's GCP project:

### Python

```python
import pulumi_gcp as gcp

gcp.logging.ProjectBucketConfig("default-logs",
    project=project_id,
    location="global",
    bucket_id="_Default",
    retention_days=90,
    enable_analytics=True,
)
```

### TypeScript

```ts
new gcp.logging.ProjectBucketConfig("default-logs", {
  project: projectId,
  location: "global",
  bucketId: "_Default",
  retentionDays: 90,
  enableAnalytics: true,
});
```

`_Default` is the auto-created bucket every GCP project starts with. Pulumi
adopts the existing bucket on first `pulumi up` (you may see "creating" in
the diff — it's really an in-place adoption).

## Verifying

After the apply:

```bash
gcloud logging buckets describe _Default \
    --location=global \
    --project=<project> \
    --format='value(retentionDays,analyticsEnabled)'
# → 90  True
```

Then in the GCP console: Logging → Logs Explorer → "Analytics" tab should
be available. Try:

```sql
SELECT
  json_value(json_payload, '$.user_id') AS user_id,
  SUM(CAST(json_value(json_payload, '$.cost') AS FLOAT64)) AS total_cost,
  COUNT(*) AS turns
FROM `<project>.global._Default._AllLogs`
WHERE json_value(json_payload, '$.level') = 'usage'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY user_id
ORDER BY total_cost DESC
LIMIT 20
```

## Scope

Log Analytics is per **log bucket**, not per-project or per-deployment. By
default every agent in the project writes to `_Default`, so one upgrade
covers all agents. Per-agent slicing in queries uses the structured
fields we already emit:

```sql
WHERE json_value(json_payload, '$.source') = 'agent'
  AND resource.labels.service_name = 'super-stage'
```

Only consider creating a separate bucket if you want different retention
per log stream, isolated access scopes, or a dedicated SQL view per
team — none of that applies today.

## Cost

- **Ingestion** — free up to 50 GiB/month per project. At ~250 bytes per
  usage entry, that's 200M turns/month before the free tier ends.
- **Storage > 30 days** — $0.01/GiB/month. 90-day retention at our scale
  → fractions of a cent per month.
- **Log Analytics queries** — free.

## Caveat

`enable_analytics=True` is **irreversible**. Once the bucket is upgraded,
GCP doesn't support rolling back. No reason to, but worth knowing.
