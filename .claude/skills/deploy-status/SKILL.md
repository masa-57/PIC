---
name: deploy-status
description: Check deployment status across Railway and Modal.
disable-model-invocation: true
---

# Deployment Status Check

Check the status of all NIC deployment targets.

## Step 1: Railway API Status
```bash
railway status
```
If railway CLI is not configured, check health endpoints directly:
```bash
curl -s https://<your-railway-domain>/health | jq .
curl -s https://<your-railway-domain>/health/detailed | jq .
```

## Step 2: Modal Workers Status
```bash
modal app list
```
Check for the `nic` app. If deployed, verify functions:
```bash
modal function list
```

## Step 3: Recent Modal Logs (if issues suspected)
```bash
modal app logs nic --since 1h
```

Report a summary: Railway API (up/down), Modal workers (deployed/not), any recent errors.
