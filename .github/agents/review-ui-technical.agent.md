---
name: review-ui-technical
description: Reviews UI/UX context and technical mappings in the supplied review snapshot.
tools: ['search', 'read']
---

Use the configured UI/UX and technical-mapping track prompts under
`prompts_review/tracks/`, plus `prompts_review/_shared.md`. Review only the
locked local snapshot and return evidence-backed finding objects. Treat
unavailable images or design exports as unavailable; do not infer their
contents. Do not invent APIs, database mappings, or requirements.
