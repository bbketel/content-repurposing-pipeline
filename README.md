# Content Repurposing Pipeline — V0.1

An n8n-based automation pipeline that monitors an RSS feed, generates multi-channel 
content drafts via OpenAI, and publishes only after human approval.

## What It Does

Given a source RSS article, the pipeline:
1. Detects new articles via source_hash idempotency
2. Generates Twitter thread, LinkedIn post, newsletter draft, title options, and hashtags via gpt-4o-mini
3. Validates LLM output against a strict JSON schema
4. Notifies a human reviewer via email
5. On approval, creates a structured Google Doc draft
6. Tracks full state history in Google Sheets

## State Machine
```
NEW → PREPROCESSED → GENERATED → PENDING_APPROVAL → APPROVED → PUBLISHED
FAILED_LLM (with retry counter, max 2) → QUARANTINED
```

## Architecture

- **Orchestration:** n8n (self-hosted on Railway)
- **Storage:** Google Sheets (state machine + audit trail)
- **LLM:** OpenAI gpt-4o-mini (strict JSON output)
- **Draft destination:** Google Docs (Drive folder)
- **Notification:** Gmail
- **Idempotency:** source_hash = 32-bit hash(normalized_url + published_at)

## Production Traits

- Idempotent — reruns never duplicate items
- Schema validation on all LLM outputs
- Retry logic with quarantine after max retries
- Human approval gate before any content is published
- Full state and error tracking per item with correlation_id
- Publish guard prevents double-publishing

## Stack

- n8n 2.9.2 (self-hosted, Railway)
- Google Sheets API
- Google Docs API
- Gmail API
- OpenAI API (gpt-4o-mini)

## Schema

See [schema/google-sheets-schema.md](schema/google-sheets-schema.md)

## Architecture Notes

See [docs/architecture.md](docs/architecture.md)

## V0.1 Tradeoffs

| Decision | Rationale | Upgrade Trigger |
|----------|-----------|-----------------|
| 32-bit JS hash over sha256 | crypto blocked in n8n 2.9.2 | Volume exceeds ~10k items |
| Title + metadata only for LLM input | Budget conservation | Switch after pipeline validated end-to-end |
| gpt-4o-mini over gpt-4o | ~30x cheaper, sufficient for structured JSON | Upgrade if output quality insufficient |
| Google Sheets over database | Minimize tooling | Switch to Postgres if query complexity increases |
| Manual approval via sheet edit | Fastest V0.1 path | Replace with approval form or Slack workflow |
