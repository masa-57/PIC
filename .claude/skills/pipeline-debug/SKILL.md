---
name: pipeline-debug
description: Diagnose pipeline or worker failures by checking job status, advisory locks, and Modal logs.
disable-model-invocation: true
---

# Pipeline Debug

Systematically diagnose pipeline and worker failures across all NIC systems.

**Use the Postgres MCP server (`mcp__postgres__query`) for all SQL queries below.** Fall back to the Python script approach only if the MCP server is unavailable.

## Step 1: Check Recent Jobs

```sql
SELECT id, job_type, status, error_message, created_at, updated_at
FROM jobs
ORDER BY created_at DESC
LIMIT 10;
```

Look for:
- Jobs stuck in `RUNNING` status (possible crash or timeout)
- Jobs with `FAILED` status — check `error_message`
- Multiple `RUNNING` jobs of the same type (advisory lock should prevent this)

## Step 2: Check Advisory Locks

Check if a pipeline advisory lock is being held (prevents new runs):
```sql
SELECT pid, granted, objid
FROM pg_locks
WHERE locktype = 'advisory' AND objid = 1313423105;
```

Note: `1313423105` = `0x4E494301` (the NIC advisory lock constant).

If a lock is held by a dead process, the stale job needs its status updated:
```sql
UPDATE jobs SET status = 'FAILED', error_message = 'Manually cleared: stale lock'
WHERE status = 'RUNNING' AND job_type IN ('PIPELINE', 'CLUSTER_FULL');
```

## Step 3: Check R2 Inbox State

Count images waiting in the R2 inbox:
```bash
uv run python -c "
import boto3
from nic.config import settings

s3 = boto3.client('s3',
    endpoint_url=settings.s3_endpoint_url,
    aws_access_key_id=settings.s3_access_key_id,
    aws_secret_access_key=settings.s3_secret_access_key,
    region_name='auto'
)
response = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix='images/', MaxKeys=100)
count = response.get('KeyCount', 0)
print(f'Images in inbox: {count}')
if count > 0:
    for obj in response.get('Contents', [])[:5]:
        print(f'  {obj[\"Key\"]} ({obj[\"Size\"]} bytes)')
"
```

## Step 4: Check Modal Worker Status

```bash
modal app list 2>/dev/null | grep nic || echo "Modal CLI not configured or nic app not found"
```

If Modal is configured, check recent logs:
```bash
modal app logs nic --since 30m 2>&1 | tail -30
```

## Step 5: Check Database Image State

```sql
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN has_embedding = 1 THEN 1 ELSE 0 END) as with_embedding,
    SUM(CASE WHEN has_embedding = 0 THEN 1 ELSE 0 END) as without_embedding,
    SUM(CASE WHEN l1_group_id IS NOT NULL THEN 1 ELSE 0 END) as clustered_l1,
    SUM(CASE WHEN l2_cluster_id IS NOT NULL THEN 1 ELSE 0 END) as clustered_l2
FROM images;
```

## Step 6: Check Railway Deployment (if Railway MCP available)

Use the Railway MCP server to check the API service status and recent deployment logs. If the Railway MCP is not available, fall back to:
```bash
railway status 2>/dev/null || echo "Railway CLI not linked to project"
```

## Step 7: Report Summary

Provide a clear diagnosis:
- **Job status**: Any stuck/failed jobs and their error messages
- **Lock state**: Whether an advisory lock is blocking new runs
- **R2 inbox**: How many images are waiting to be processed
- **Modal workers**: Whether workers are deployed and responsive
- **DB state**: Image counts by processing stage
- **Railway API**: Whether the API service is healthy
- **Recommendation**: Specific next action to resolve the issue
