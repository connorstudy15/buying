# Agent release protocol v2

This preserves every v1 question, rubric, deterministic assertion, ID and split.
The only case change is an explicit user approval after the first memory turn.
Memory writes now require a browser confirmation; sending the next chat message
without approving correctly leaves the operation pending.

The runner uses AG-UI for these memory cases and resumes only the server-issued
interrupt whose tool and complete input match the frozen action. It never infers
approval from assistant text. Resume model usage is included in cost and latency.

Judge context retains complete catalogue rows and SKU rows for every product ID
in the dialogue or tool evidence, flags unknown IDs, and includes exchange rates.
It omits unrelated catalogue rows to avoid confusing a million-character table.
Rubrics and strict PASS requirements are unchanged. The manifest now fingerprints
the actual configured catalogue, rather than the obsolete v1 fixture.
