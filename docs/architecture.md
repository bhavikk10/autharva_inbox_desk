# Architecture

Inbox Desk separates conversation interpretation from time-based attention. The model interprets what the messages mean; application code validates that extraction and determines how its timing affects the inbox.

## Data flow

```text
Email provider → normalized messages → visible thread at the selected time
              → model extraction → schema and evidence validation
              → date resolution and attention policy → assessment with evidence
```

An `EmailProvider` interface separates sample inputs from Gmail ingestion. Each message preserves its ID, sender, recipients, direction, timestamp, body and attachment metadata. Gmail category labels remain available to the interface. Attachment contents are not analyzed.

Only messages available at the selected evaluation time enter analysis. Message content is supplied as untrusted data, with instructions to extract obligations rather than follow instructions embedded in emails.

## Model extraction

The analyzer interface supports Ollama, GLM and Gemini with the same validated structured schema. Extraction includes conversation state, relevance, intent, blockers, recommendations and an obligation ledger. Each required item carries its owner, status, importance, explicit urgency, commitment materiality and supporting source evidence. Optional suggestions are kept separate from required obligations.

For dates, the model returns the raw phrase and its source message ID. It does not calculate a deadline or receive the evaluation clock. Code anchors the phrase to message metadata, taking explicit timezones into account. Supported expressions include explicit dates, tomorrow, weekdays, next week and month-end. Unsupported or ambiguous expressions remain unresolved with an explanation.

Referenced IDs must exist in the visible thread. Ollama generation constrains source references to the visible message IDs. Evidence quotes and raw date expressions must match their source wording; email line wrapping, whitespace and curly versus straight quotation marks are normalized for comparison. Claimed resolutions require later supporting evidence. A model may receive one bounded regeneration request with the validation diagnostic, after which the result still undergoes full validation.

These checks reject malformed or unsupported output, but cannot prove semantic correctness. An acknowledgement may be mistaken for an answer, or an answered request may remain open. Changing the model can change these judgments even when the surrounding pipeline stays the same.

## Attention and time

The ordered policy evaluates explicit urgent actions, important overdue obligations, missed material commitments, unanswered important asks, routine actions, proposal staleness and appropriate waiting. Sales conversations use a commercial relevance policy; Gmail conversations also support a general inbox policy for personal, transactional and informational mail.

Date-only commitments use 09:00 and 17:00 boundaries in the applicable timezone: future waiting becomes due-today attention at 09:00 and overdue attention at 17:00. Explicit deadline times take precedence. The system timezone is detected when no override is configured, and users can choose a timezone in the interface. Available original sender timezone metadata anchors relative expressions; missing metadata is handled through the configured fallback and surfaced in notes.

Unanswered outbound messages are counted in code. The model identifies semantically non-substantive inbound replies; these do not reset the count. Three unanswered outbound messages suppress generic chasing, while a separate urgent obligation can still require attention. Explicit deferral suppresses generic staleness until the agreed date. Advisory recommendations never raise the tier, and a scheduled meeting does not establish that it occurred.

## Persistence and reuse

SQLite stores threads, messages and analysis snapshots. Extracted items remain in snapshot JSON alongside the actual model response and provenance. An operations table persists queued jobs, attempts, review notes and draft history.

Extraction cache identity includes visible-message content, provider, model, prompt version and schema version. Evaluation time is excluded. If the visible messages are unchanged, moving the clock reuses extraction and recomputes the policy. A new reply changes the input and requires fresh extraction.

Saved runs preserve the provider, model, input identity and creation time. Replay uses actual completed model outputs, never fabricated assessments. Shareable exports exclude private Gmail conversations; historical results with unavailable input versions are identified explicitly.

## Queue and failures

The application persists FIFO analysis jobs and runs a continuous worker. GLM calls are serialized across the local application and evaluation processes to respect the account's one-stream restriction. This coordination is designed for a single host, not a distributed deployment.

Primary analysis has a configurable total execution budget, including retries and provider-lock waits. If a previous remote generation is still cooling down, GLM reports that immediately rather than spending the next request's budget waiting. An optional, explicitly enabled Ollama fallback receives a separate budget and produces its own validated result and cache entry. The primary failure remains recorded, and provenance identifies the provider that actually succeeded.

Missing configuration, provider errors or invalid output leave an explicit error or unassessed state. Failure is never converted into T4. Reply drafts use the configured model and remain editable text; there is no Gmail sending operation.

## Scope

This is a single-workspace application with read-only Gmail access, manual synchronization and human review. It does not provide background Gmail polling, attachment-content extraction, autonomous follow-ups or multi-user authentication. The local OAuth flow and workspace storage require changes before serving private mail to public users.
