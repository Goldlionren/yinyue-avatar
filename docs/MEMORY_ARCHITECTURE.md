# Memory architecture

## Runtime files

Structured long-term memory is independent of scene state:

```text
STATE_DIR/memory/events.jsonl
STATE_DIR/memory/summary.json
STATE_DIR/memory/backups/
```

`events.jsonl` is the authoritative append/status-preserving event set. Each
record has a UUID, timestamp, allowed type, importance 1–5, bounded non-empty
text, source id, active/superseded/resolved/archived status, supersedes id, and
canonical SHA-256 dedupe key.

Allowed types are relationship event, shared experience, user preference,
commitment, important fact, and open thread. `memory-add` rejects duplicates;
`memory-supersede` marks the old record and adds a replacement;
`memory-resolve` changes status without deleting. No command automatically
deletes events or backups.

## Deterministic summary

The helper selects active events, deduplicates by key, sorts each category by
importance descending then time descending, applies a per-category maximum and
global text-character budget, validates the full candidate, backs up the old
summary, and atomically replaces it. Summary failure rolls events back and
leaves the old summary intact. No external or embedded LLM is used.

`context` loads `summary.json` only. It never opens `memory/events.jsonl`.
Legacy `state.memory.recent_events` or legacy summary lines are imported once
when no structured events exist. `--remember` maps to shared experience,
importance 3, with the same dedupe logic.

## Meaningful recent history

Recent conversational context is separately selected from a bounded reverse
scan of raw history. Only allowlisted business events are eligible. Event id
and compact business fingerprint dedupe are applied; relationship,
commitment, and pending-delivery events receive priority; selection obeys
eight-event and 4000-character defaults, then returns chronological order.
Corrupt JSONL lines are counted and skipped. Relationship before/after objects
are replaced with a compact revision summary.

Persona and lore remain files in the Skill. Relationship remains in state.
None of persona, lore, relationship prose, memory summary, memory events, or
raw history is injected into the ComfyUI prompt.
