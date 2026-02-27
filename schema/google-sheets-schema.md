# Google Sheets Schema — content_pipeline

## Sheet: Sheet1 (20 columns A–T)

| Column | Field | Type | Description |
|--------|-------|------|-------------|
| A | source_hash | string | 32-bit hash of normalized_url + published_at. Idempotency key. |
| B | source_url | string | Original article URL |
| C | source_title | string | Article title |
| D | source_published_at | string | RSS publish date |
| E | state | string | Current state machine position |
| F | retry_count | integer | Number of LLM generation attempts |
| G | last_error | string | Most recent error message |
| H | prompt_version | string | Prompt version used for generation |
| I | model | string | LLM model used |
| J | llm_output_raw | string | Raw validated JSON output from LLM |
| K | validation_status | string | VALID or INVALID |
| L | generation_attempt | integer | Increments on each generation |
| M | approval_form_url | string | Reserved for future approval form |
| N | approved_by | string | Reviewer identifier |
| O | approved_at | string | Approval timestamp |
| P | published_at | string | Publish timestamp. Null until published. |
| Q | draft_destination_url | string | Google Doc ID of generated draft |
| R | correlation_id | string | UUID for execution log tracing |
| S | created_at | string | Row creation timestamp |
| T | updated_at | string | Last update timestamp |

## State Values

| State | Meaning |
|-------|---------|
| NEW | Item detected, not yet processed |
| PREPROCESSED | Content normalized, ready for LLM |
| GENERATED | LLM output validated successfully |
| PENDING_APPROVAL | Awaiting human review |
| APPROVED | Human approved, ready to publish |
| PUBLISHED | Draft created, published_at set |
| FAILED_LLM | LLM generation or validation failed |
| QUARANTINED | Exceeded max retries, requires manual intervention |
