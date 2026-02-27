# Architecture Notes — Content Repurposing Pipeline V0.1

## Design Principles

- **Architecture before tooling** — state machine and idempotency designed before 
  any node was built
- **Deterministic preprocessing before LLM** — content is cleaned and structured 
  before any LLM call
- **LLM for generation only** — no control logic delegated to the LLM
- **Human approval before publish** — no automated publishing path exists
- **Explicit state transitions** — every state change is persisted immediately

## Workflow Structure

### Main Workflow — content-pipeline-v0.1
Trigger: Schedule (every 15 minutes)

1. Fetch RSS feed via HTTP Request
2. Parse XML to JSON
3. Read all existing sheet rows (Execute Once)
4. Code node cross-references incoming hashes against existing records in memory
5. New items only proceed — existing items skipped regardless of state
6. Upsert identity fields for new items
7. Preprocess — build content block from title + metadata
8. Build OpenAI request body
9. HTTP Request to OpenAI /v1/chat/completions
10. Parse and validate LLM JSON output against required schema
11. Retry logic — increment counter, quarantine after max 2 retries
12. If valid — set PENDING_APPROVAL, send Gmail notification, persist state

### Approval Workflow — content-pipeline-approval-v0.1
Trigger: Schedule (every 15 minutes)

1. Read all sheet rows
2. Filter for APPROVED state + published_at empty (double-publish guard)
3. Build Google Doc content from llm_output_raw
4. Create Google Doc (title only — API constraint)
5. Update Google Doc with full content
6. Upsert PUBLISHED state, published_at timestamp, and Doc ID

## Key Decisions

See V0.1 Tradeoffs in README.md

## Known Gaps (V0.2 Targets)

- Full article body fetch and HTML stripping
- YouTube as second source type
- Repair prompt on LLM validation failure before retry
- Daily summary email (counts by state)
- Approval form replacing manual sheet edit
- sha256 hash replacing 32-bit JS hash
