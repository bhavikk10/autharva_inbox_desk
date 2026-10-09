# Workflow

Inbox Desk presents conversations on the left and the selected thread's assessment, open items, recommendations and source messages on the right. Search, attention filters and inbox controls help focus the review.

## Choose conversations

Use the included conversations or import mail from a connected Gmail account. Gmail settings supports connecting additional accounts and switching between saved connections. Imports and synchronization are scoped to the selected account; previously imported conversations are retained.

Choose a Gmail category or custom search and the number of matching conversations or messages. Message selection still downloads the full corresponding threads. Spam and Trash are excluded unless enabled; all-match imports are capped at 5,000 conversations. Imports paginate, pace requests and report progress and skipped items.

The import control lets users keep the included conversations or clear them from the active workspace after a successful import. Saved assessments are retained, and samples can be restored through the information menu. Sample conversations and imported mail retain distinct origins in the underlying data.

## Set the evaluation time

Today selects the current time in the chosen timezone. Tomorrow selects the same local clock time on the next date. The calendar supports other evaluation dates and times, and invalid or ambiguous daylight-saving times require clarification.

The selected time controls which messages are visible and when extracted obligations become due. Moving the clock changes attention without another model call if the visible messages stay the same. The included conversations have fixed dates, so historical exploration uses the calendar.

## Analyze and inspect

Request analysis for a conversation or the current inbox. The queue panel shows queued, running, completed and failed work. GLM requests are processed one at a time; valid matching assessments can be reused.

An accepted assessment displays its attention level, reasoning, open obligations and recommended next action. Evidence links highlight the stored source messages. Provider provenance shows which model actually produced the extraction, including an explicitly enabled fallback when used. An error remains visible if neither provider returns valid output.

Filtering or searching keeps the detail pane aligned with a visible conversation. If no conversation matches, the detail pane clears. Sorting preserves the selected conversation and keeps its row in view.

The assessment header identifies the saved model output and its run time. **Analyze again** requests a fresh result for that conversation; bulk analysis can reuse matching output. Opening a historical saved run switches to an explicitly marked read-only view with live analysis disabled until returning to the inbox.

Check that each open item is still unresolved and that ownership and deadlines reflect the conversation. The tier is an aid to prioritization; the source messages remain the basis for a decision. Model explanations and evidence references do not guarantee correct interpretation.

## Review, reply and sync

Analysis history preserves previous results. Correction controls record a human judgment and explanation separately from the original assessment, allowing disagreements to be inspected without rewriting model history.

Generate or edit a reply draft for review, then copy it into the email client if appropriate. Inbox Desk cannot send, modify, relabel, archive or delete Gmail messages.

After a reply arrives in Gmail, synchronize the selected account's imported conversations or refresh the chosen thread. New messages change the extraction input; analyze again to assess which obligations were answered. Unchanged threads reuse matching results. The sample-message composer supports the same update-and-reanalyze flow locally without sending email.

## Browse saved runs

Choose **Browse demos & saved runs** from the information menu to inspect completed assessments across providers. Saved-run browsing makes no model request and preserves the original provenance. A changed conversation cannot silently use an incompatible old extraction.

Saved results support repeatable inspection when an API is unavailable. Live analysis, synchronization and reply generation remain separate actions with their own progress and errors.
