---
name: create-data-context
description: "Create, update, inspect, or repair Data Analytics semantic layers. Use when the user asks to save data context or create a semantic layer that future Data Analytics work can inspect and cite."
---

# Create Data Context

This skill creates and maintains semantic-layer skills for Data Analytics. A semantic-layer skill is an explicit artifact the user can inspect and cite later. It captures how future analyses should interpret the data, for example which metric definition is canonical, which dashboard or table is the best source of truth, and what caveats should be checked before answering.

Data-task routing is owned by the Data Analytics `index` skill. If the user wants Data Analytics to do work with data now, route to `index`, whether the work starts from connected sources, uploaded files, pasted tables, sample data, or an existing semantic layer. Examples include answering a metric question, building a report, or checking a dataset.

Use this skill only when the user asks to save data context or create, update, inspect, or repair a semantic layer.

## Runtime Routing

If `surface = chatgpt_web` and `mode = work_mode` are both positively identified, do not start semantic-layer creation, update, inspection, repair, local skill writing, or recurring refresh setup. Return control to the Data Analytics `index` workflow and use the information as current-session context. If the user asked to save it, explain that web Work Mode can use it in the current conversation and offer a current-run metric-definition note, source plan, notebook, or report instead.

Do not infer web Work Mode from missing tools or local-environment details. Outside positively identified web Work Mode, keep this skill's existing behavior unchanged.

## Skill Configuration

### Audience And Language

Write for Data Analytics users, not plugin maintainers. Explain what context would improve the current or future analysis in practical terms. Avoid implementation terms such as raw state paths, connector ids, cache, runtime, metadata, or preflight unless the user asks for debugging details.

### Source Links

When referencing sources inline, prefer clickable Markdown links over plain labels whenever a useful URL exists. Use the source title, record name, channel/thread, or meeting/date as the link text. Use plain labels only when no useful link is available.

## Semantic Layer Setup

Use this flow when the user wants to create or maintain a semantic layer. If they are not ready to create the layer yet, use the same flow to produce a short source plan for what the semantic layer needs.

The output is a visible skill or plan. Build the semantic-layer skill when enough source-backed detail exists to make it useful. When the available detail is still thin, return a practical plan that explains what source to collect next and why.

## Creating Or Updating The Layer

Create one semantic layer per coherent product, business, metric, source, or reporting area unless the user explicitly asks for a broader shared layer. Infer the area from the provided context when it is clear; ask only when the answer changes the crawl, destination, or resulting skill.

Default local creations to `$CODEX_HOME/skills/<area>-semantic-layer` unless the user chooses another destination. Ask before placing a generated semantic-layer skill inside a plugin.

Before crawling, build a data-source list that explains what was checked, what is missing, and which sources are lower-confidence. For direct creation or draft-file work, write it to `references/source-inventory.md`; for planning-only work, return it in chat.

Use source-backed evidence. Favor durable sources such as transformation code, tests, maintained metric docs, and verified dashboards over looser signals such as query history or team discussion. If sources disagree, keep the conflict visible instead of choosing silently.

Keep generated semantic-layer skills compact. Put detailed metric definitions, tables, query patterns, caveats, and evidence into linked references using `references/semantic-layer/skill-template.md`. Preserve provenance and avoid copying raw sensitive data, credentials, row-level examples, or long private messages into generated files.

Read `references/semantic-layer/weekly-polling-automation.md` only before offering or creating recurring refresh. Weekly refresh is optional and requires user approval unless the user directly asks for it.

Return the created or updated path, source coverage, validation result, and future-use guidance so the user can cite the semantic layer directly in later prompts.

## Output Contract

For semantic-layer work, report what was created, updated, inspected, or repaired; source coverage; validation results; and the exact path the user can cite later. If the request is ordinary data work, say that it should be routed through `index`.
