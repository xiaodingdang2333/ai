---
name: index
description: "Route Data Analytics plugin-level requests and broad analytics work to the right focused workflow. Use when Data Analytics is at-mentioned, or for analytics requests involving data, metrics, dashboards, reports, charts, notebooks, spreadsheets, KPIs, market sizing, or semantic layers."
---

## Eligibility gate (read before routing)
Use this plugin only when resolving the request requires structured records, numeric measures, quantitative evidence, a dashboard/metric definition, or a business/product decision grounded in such evidence. Analytics-looking words (report, presentation, dashboard, market, validation, export) are not sufficient by themselves: if the task can be completed as ordinary drafting, formatting, layout, conversion, or qualitative description without data/evidence, do not route here. Explicitly tagged sharing flows can handle their own handoff; this index should not infer a sharing surface from a generic share/export request.

Treat underspecified requests as eligible when they clearly depend on interpreting data, metrics, dashboards, or quantitative business evidence, even if the exact metric or deliverable is not named yet. Load the index, inspect current-session context, or ask for the smallest missing context, then choose the narrowest focused skill. Do not require a named metric upfront; do reject purely mechanical transformations, formatting, code fixes, syntax snippets, or generic explanations that do not require interpreting evidence.

When eligible, choose the most specific analytical skill; when uncertain, ask one clarification rather than opening a generic report/export skill.

## Launch/segment decision cue
Eligible product-analytics requests can ask for a product launch, rollout, prioritization, segmentation, experiment readout, A/B test interpretation, or ship/hold/iterate tradeoff recommendation under stated or to-be-collected assumptions/constraints. Treat those as analytics workflows when they cite metrics, confidence/uncertainty, guardrails, segments, or structured evidence, even when the first step is context collection; pair context with product-business-analysis and build-report only when a durable analytical report is requested.

## Metric definition/source-of-truth disputes
When teams disagree about which metric definition, dashboard, extract, owner, or source of truth should control a decision or executive reply (for example revenue/ARR, activation, retention, funnel, or regional totals), route as analytics even if the immediate output is a short Slack/email recommendation. Prefer `analyze-data-quality` for comparability/backfill/grain/source conflicts and `design-kpis` for canonical definition/guardrail ownership; use both when the request asks which definition should govern.

## Staged analytics workflow follow-through
If one request says to first ask for/collect owner, constraints, assumptions, or context and then use that information for an analytics decision, recommendation, dashboard, or report, do not stop after only asking the clarification. When the overall request is eligible under the analytics gate, first read `.agents/skills/gather-business-context/SKILL.md`, then the most relevant analysis skill and, if needed, `.agents/skills/build-report/SKILL.md`. For a durable narrative deliverable in this staged pattern (memo, one-pager, readout, or brief), read `.agents/skills/build-report/SKILL.md` before clarifying. Ask the clarification after loading those skills if information is still missing.



# Skill Purpose

Route broad Data Analytics requests to the right focused workflow. Treat invocation of this index as strong intent to use this plugin when the request needs quantitative evidence, source verification, metric reasoning, or a decision grounded in data; prefer focused analytics skills over generic report/export handling.

## Skill Configuration

### Runtime Routing

Classify `surface` and `mode` separately, and only from positive system or developer signals or genuinely exclusive tools:

- `surface = codex_desktop` when the environment is explicitly identified as Codex desktop or desktop-only `codex_app` tools are available.
- `surface = chatgpt_web` when the environment is explicitly identified as ChatGPT in a web browser.
- `mode = work_mode` when the environment is explicitly identified as Codex Work Mode.
- `mode = chat` when the environment is explicitly identified as standard ChatGPT chat.
- Otherwise set the relevant value to `unknown`.

Never infer mode from surface, missing tools, tool failure, operating system, file paths, sandbox details, or network details. Explicit context overrides tool availability. Treat `web_work_mode` as true only when `surface = chatgpt_web` and `mode = work_mode` are both positively identified.

For positively identified `web_work_mode` runs:

- Do not use structured intake or call `request_user_input`. Ask any necessary task-selection or fallback question directly in the normal conversation, with at most two or three concise choices.
- Do not route to `create-data-context` or create, update, or repair a semantic-layer artifact. Use current-session context instead. If the user asks to save context, explain that this route can use it for the current conversation and offer a current-run metric-definition note, source plan, notebook, or report.
- Do not select Data Analytics MCP UI surfaces, including inline chart/table widgets or MCP artifact reports and dashboards. MCP servers and other callable tools remain valid data sources. Use native Work Mode chart or table rendering when available for inline visuals, and use HTML for a durable report or dashboard unless the user selected a connected BI or another non-MCP destination.

Outside positively identified `web_work_mode`, keep the existing desktop and portable behavior. For an unknown environment, use portable conversational behavior and do not disable a capability merely because a signal is absent.

### Saved Data Context And Semantic Layers

Ordinary analytics workflows do not require saved data-context setup. Use context supplied in the current request, current conversation, connected source reads, uploaded files, pasted artifacts, local repo files, or explicitly named semantic layers. Outside `web_work_mode`, route to `create-data-context` only when the user asks to save data context or create, update, inspect, or repair a semantic layer. In `web_work_mode`, keep that information current-session only and follow `Runtime Routing`.

### Guided Flow And Source Setup

This index owns task selection, setup-adjacent routing, and guided workflow continuation. Apply its stateless first-task flow after plugin intent is established for get-started requests, open-ended prompt discovery, uploaded or demo data, and walkthrough questions. Send pure capability summaries to `Broad Orientation And Help Requests`. If the user already supplied a concrete task, skip intake and treat it as a custom question.

Use only the current conversation, visible installed plugins and skills, current-run tool results, uploaded or pasted context, and local files. Never ask where to find data or show a source, project, dashboard, table, SQL, file, connector, or provider picker. Do not create saved data context from this flow unless the user explicitly asks for that.

#### First-task intake

Use the structured form contract below only when `surface = codex_desktop` and `request_user_input` is available. In `chatgpt_web`, `work_mode`, or an unknown environment, do not emit a structured form or schema and do not call `request_user_input`; present the same task or fallback choices compactly in normal conversation. A positively identified `web_work_mode` run must always use this conversational path.

1. If the user supplied a concrete task, skip intake and continue at `Custom-question access`.
2. Otherwise inspect only the runtime-provided installed Apps and Plugins inventory plus callable tools already visible in the session, including custom MCP servers and other callable tools that can read the needed source. Do not read connector records, call `functions.list_available_plugins_to_install`, or treat `.app.json` and [DEPENDENCIES.MD](../../DEPENDENCIES.MD) declarations as installed. If tools are lazy-loaded, use `tool_search` by the name, source type, or task-relevant capability of an already-visible or user-named connector, custom MCP server, or other callable tool to verify callability; do not search only a fixed provider catalog.
3. If at least one useful connected source exists, ask one `request_user_input` question with exactly three options: two distinct tasks backed by existing installed connectors or callable tools, followed by `Upload your own`. Prefer distinct source families; if fewer than two are useful, derive multiple non-duplicative tasks from the same connected source's capabilities. Never include sample, installation, or unsupported options.
4. If no useful connected source exists, offer exactly `Upload data` followed by `Use sample data`. Do not add `Connect a data source`.

Use `Dashboard`, `Report`, or `Data task` as the header. Ask `What should the dashboard be about?` or `What should the report be about?` when the artifact is known; otherwise ask `The Data Analytics plugin helps Codex turn data into insights, recommendations, and decision-ready artifacts. Try it out with one of these prompts:`. Keep labels under 80 characters, omit recommendation suffixes, and preserve the built-in free-form Other field for a custom question. If `request_user_input` is unavailable, render the same choices compactly in chat. Canceled or empty submissions defer the flow.

Connected-source form: `{ id: "data_task", options: [{ label: "{connected task 1}", description: "{connected-source description 1}" }, { label: "{connected task 2}", description: "{connected-source description 2}" }, { label: "Upload your own", description: "Upload or paste your own data and produce an analytics report with findings and next steps." }] }`.

No-source form: `{ id: "data_task", options: [{ label: "Upload data", description: "Upload or paste your data and produce an analytics report with findings and next steps." }, { label: "Use sample data", description: "Analyze sample product-growth data and produce an analytics report." }] }`.

#### Selection handling

- Connected-source task: use its existing connector or callable tool and start the implied focused workflow, usually `$product-business-analysis`, `$visualize-data`, and `$build-report`. Choose the controlling source automatically; do not open plugin installation. If the source unexpectedly cannot provide usable evidence, use the fallback form below.
- `Upload your own` or `Upload data`: ask for the smallest useful export, SQL result, data shape, screenshot, metric definition, or file, then wait.
- `Use sample data`: start the demo contract immediately without another confirmation.
- Other text: treat it as a user-authored custom question and continue at `Custom-question access`.

Do not ask the user to choose a provider, project, table, dashboard, query, or export. Ask for source confirmation only when already-available sources conflict in a way that changes the answer.

#### Custom-question access

Only a concrete task supplied in the user's message or the intake form's Other field may trigger installation. Choose the focused workflow, then decide whether an existing plugin, app, connector, custom MCP server, other callable tool, uploaded or pasted artifact, local file, or current-run context provides enough fresh, authoritative evidence. If yes, choose the controlling source and start.

For missing evidence, check visible or lazy-loadable custom MCP servers and other callable tools that can read the needed source before native connector installation. Treat a custom MCP server or other callable tool as related when its server or tool name, description, action schema, or the user-named source indicates it can read the needed source category. Configured `preferred_plugins`, `.app.json`, and [DEPENDENCIES.MD](../../DEPENDENCIES.MD) are routing hints, not the source universe.

If required evidence is still missing and a plausible connector lane exists, use [DEPENDENCIES.MD](../../DEPENDENCIES.MD) to map source families and call `functions.list_available_plugins_to_install` once. If current-run context already lists exact suppressed plugin-install ids, remove those exact ids; do not run the legacy preflight just to obtain suppressions. Then call `functions.request_plugin_install` sequentially for every exact returned candidate useful to the task. Do not guess ids, narrow to one generic "best" candidate, stop after the first useful candidate, call installs in parallel, or use `request_connector_setup`. When an install is declined or unconfirmed, record that exact id with `record_plugin_install_suppression.py` and continue with other useful candidates.

Warehouse exception: if the custom task needs structured data, no warehouse is usable, and the user named none, keep every returned warehouse candidate. Ask which warehouse to use, naming all of them; install only the selected exact candidate. If one is returned, offer it directly. Never choose by manifest order or configured preference.

If setup is unavailable, declined, unconfirmed, canceled, or still yields insufficient evidence, you MUST ask this fallback question before ending the same turn: `{ id: "fallback_next_step", question: "I don't have enough data to complete this task. How do you want to proceed?", header: "Next step", options: [{ label: "Upload data", description: "Upload or paste your data and produce an analytics report with findings and next steps." }, { label: "Use sample data", description: "See a clearly labeled synthetic product-growth demo; it will demonstrate the workflow without answering the real-data question." }] }`. Do not add another custom option or recommendation suffix.

After successful setup, start the focused workflow automatically. Do not show post-setup flow-control choices.

#### No-source completion invariant

Any path that determines there is no usable data for the active task MUST offer `Upload data` and `Use sample data` before the turn ends. This includes no useful connected source, a required source being unavailable, an install tool being unavailable, an install prompt being declined, dismissed, canceled, or left unconfirmed, a successful install that still cannot return usable evidence, and a connected source that unexpectedly lacks sufficient evidence.

Do not end with only a missing-source explanation, an installation suggestion, or an instruction to connect a source and retry. An installation prompt may come before the fallback question, but it never replaces the fallback question unless setup succeeds and the source returns usable evidence in the current run. Use the exact `fallback_next_step` form above for concrete tasks. For `Use sample data`, say explicitly that the bundled demo is synthetic and will demonstrate the workflow rather than answer the user's real-data question.

#### Connected-source option copy

Treat a visible installed or callable surface as warehouse-like when its name, description, or actions indicate warehouse, SQL, query, table, schema, dataset, or database access. Rank useful options by source-of-truth fit: warehouse/source system first, then BI, product analytics, GitHub, tabular Drive/files, and finally the best-fit document or communication source. A task must remain executable through its connected source.

Use source-specific labels for non-warehouse tasks and keep warehouse labels provider-neutral. If one connector fills multiple slots, vary the task by real connector capability instead of repeating copy. These are defaults, not hidden prompts:

| Source | Label | Description |
| --- | --- | --- |
| Warehouse or source system | `Analyze business data` | Analyze warehouse or source-system data for trends, segments, outliers, and next steps. |
| BI/dashboard | `Analyze dashboard trends` | Analyze dashboard or BI data for trends, gaps, and follow-up cuts. |
| Product analytics | `Analyze product usage` | Analyze events, funnels, retention, experiments, and behavior changes. |
| GitHub | `Analyze GitHub activity` | Analyze issues, pull requests, reviews, and blockers. |
| Email | `Analyze email trends` | Analyze threads for themes, trend signals, follow-ups, and next steps. |
| Drive | `Analyze Drive files` | Analyze relevant Drive data for findings and next steps. |
| Calendar | `Analyze meeting patterns` | Analyze meeting topics, attendees, length, frequency, and next steps. |
| Notion | `Analyze Notion content` | Analyze pages and databases for project status, decisions, and themes. |
| Slack | `Analyze Slack activity` | Analyze messages for active topics, blockers, decisions, and follow-ups. |
| Teams | `Analyze Teams messages` | Analyze chats and channels for topics, actions, blockers, and decisions. |
| SharePoint | `Analyze SharePoint files` | Analyze relevant SharePoint data for findings and next steps. |

#### Demo data

Show `Use sample data` only when no useful connected source exists or a selected workflow still lacks usable evidence. Resolve [demo-product-growth.csv](../../assets/demo-product-growth.csv) relative to this skill, label it synthetic, analyze it with reproducible SQL without inventing rows or findings, and route it through `$product-business-analysis`, `$visualize-data`, and `$build-report`; let `$build-report` choose exactly one report delivery mode.

### Source Discovery And Verification

Use the relevant semantic layer first when one exists. Treat it as the starting map for candidate metrics, tables, joins, filters, caveats, source precedence, and known conflicts.

Do not stop at the semantic layer or the first plausible source. Search across the relevant available company source lanes, including structured data or data warehouses, source systems, dashboards, company docs, team communication, notebooks, code repositories, and other connected company knowledge or data that could change the answer. When choosing among connected sources for analytical data, prefer data warehouses and source systems that own the underlying records before BI dashboards, product analytics summaries, spreadsheets, docs, or conversations.

For source-backed analytical work, always verify through live source reads. When the answer depends on data, run fresh data queries against the available structured-data sources before drawing conclusions, even when the semantic layer already names likely tables or definitions.

Use the combined evidence to determine which source controls the answer, note meaningful disagreements, and state why the selected source is authoritative.

### Source Access Guardrail

Before querying sources, building artifacts, or drawing conclusions, determine whether the answer requires a specific source of truth.

If a required source is unavailable, stop that path. Tell the user what source is needed and do not treat weaker substitutes as equivalent. Then apply the mandatory `No-source completion invariant`: offer uploaded data or the clearly labeled synthetic demo before ending the same turn.

If the missing source is only optional enrichment, continue with the strongest available evidence and label the gap when it materially affects the answer.

### Audience And Language

Write for Data Analytics users, not plugin maintainers. This applies to final answers, setup/status readbacks, failure explanations, tool preambles, and mid-turn progress narration.

Translate implementation work into practical Data Analytics impact: what Data Analytics is checking, setting up, saving, or preparing, and why it matters. Avoid implementation terms such as preflight, state file, cache, raw connector id, heartbeat, targetThreadId, schema, API, runtime, metadata, and provider taxonomy unless the user asks for debugging details.

### Source Links

When referencing sources inline, prefer clickable Markdown links over plain bracket labels whenever the source exposes a useful URL. Use the source title, record name, channel/thread, or meeting/date as the link text, for example a clickable Markdown link whose visible text is `Meeting notes: May 19` or `Slack thread: May 15-21`. Use plain text labels only when no useful URL or stable connector-visible link is available, and say `(no useful link available)` when that absence matters.

### Routing

#### Run Order

Every Data Analytics plugin run follows this order:

1. Handle pure capability-summary requests with `Broad Orientation And Help Requests`; apply `Guided Flow And Source Setup` to open-ended action or prompt discovery, first-run task selection, explicit guided-flow requests, and setup-adjacent prompts that should choose and run a data task before deeper setup.
2. If the user asks to save data context or create, update, inspect, or repair a semantic layer, route to `create-data-context` unless the request is clearly part of first-task guided flow or Runtime Routing identifies `web_work_mode`; in `web_work_mode`, keep the context current-session only and offer a current-run note, source plan, notebook, or report instead.
3. If the user asks to answer a data question using an existing semantic layer, treat the layer as context and continue with the appropriate analytics workflow.
4. Apply semantic-layer lookup only when the user names a semantic layer or path, or a relevant semantic layer is already discoverable from the current runtime.
5. Apply Source Discovery And Verification before source queries, document search, notebook work, report building, dashboard wiring, or conclusions.
6. Apply the Source Access Guardrail before source queries, document search, notebook work, report building, dashboard wiring, or conclusions.
7. Choose the response mode: `inline` for bounded lookups and `report` for explanations, decompositions, recommendations, or larger analytical answers.
8. Select the minimal primary/supporting skills, then do one companion-skill pass across installed skills for clearer non-analytics surfaces, semantic layers, or methods.
9. Read and follow the selected skill bodies before source queries, report building, supporting-skill execution, or final drafting.
10. Before final response, apply the focused workflow's completion gates. Treat create-data-context output as optional unless the user explicitly asked to save data context or work on a semantic layer.

#### Response Mode

Use `inline` for bounded factual or computational answers that can be delivered in chat without a durable artifact: metric lookups, schema or table questions, one-cut rankings, and simple comparisons.

Treat short quantitative prompts as Data Analytics work when answering them requires explaining how numbers compare, break down, concentrate, or move across multiple values, groups, or time points. Keep these routes lightweight by default: use `inline` for bounded answers and escalate to `report` only when the user asks for explanation, diagnosis, recommendation, or a durable artifact.

Use `report` for explanation, diagnosis, decomposition, synthesis, recommendation, or larger analytical answers whose value materially improves from a durable artifact. When the user asks to interpret analytical source material or reviewed results, choose report mode when the answer needs evidence-backed narrative, caveats, source metadata, or a reader-facing artifact. $product-business-analysis, $metric-diagnostics, and $kpi-reporting imply `report`; every `report` route includes $build-report unless the user explicitly waives file or report creation.

After choosing `inline` or `report`, use `$visualize-data` when a visual would make the result easier to understand, especially for category comparisons, part-to-whole breakdowns, rankings, movement over time, or more than a handful of comparable values, rows, categories, or time points. Prefer a visual pass over a scan-heavy table, and let `$visualize-data` choose the form, decide whether to render a chart, and align any table or prose to the visual takeaway.

#### Skill Selection

- Pick the smallest useful set of primary/supporting skills.
- For report-mode runs, state the selected route once in a progress update, such as `Route: product-business-analysis + product semantic layer + build-report`.
- Use this index's guided gate for source/task setup across all Data Analytics skills, including explicit setup, get-started, first guided workflow, setup-status, offline/demo fallback, walkthroughs, and active guided-flow continuation requests. Keep that gate free of unsolicited saved data-context or semantic-layer creation.
- Use `create-data-context` for explicit semantic-layer setup or maintenance outside ordinary data work.
- Treat a plugin mention as a starting point, not a boundary. Add an installed external skill whenever it is the clearer owner of a complementary subtask, runtime surface, delivery surface, artifact type, or domain-specific method.
- Do not reject an external skill merely because a bundled Data Analytics skill partially overlaps with it.
- Do not maintain worked route recipes here. Once selected, the chosen skills own detailed step order, supporting triggers, and output contracts.
- When a request maps to a primary workflow, load that workflow skill directly. For example, a KPI design prompt must read `$design-kpis`, a dashboard prompt must read `$build-dashboard`, a TAM/SAM/SOM prompt must read `$market-sizing`, a metric movement prompt must read `$metric-diagnostics`, and a recommendation-oriented product or business decision prompt must read `$product-business-analysis`.

If several focused skills apply, sequence them in the order that creates the most useful analyst workflow. For example, metric diagnostics may precede KPI reporting, semantic-layer setup may precede dashboard or report work, and product-business analysis may feed a recommendation-ready report. Keep this index as a router; do not perform focused workflow logic here.

Before finalizing future Data Analytics instruction edits that touch guided-flow or create-data-context behavior, run `python3 plugins/data-analytics/skills/create-data-context/scripts/validate_data_context_contract.py` from the repository root. This validator checks that guided flow and semantic-layer setup stay routed to their owning skills.

Prefer examples that route to focused skills without extra setup, such as:

```text
@Data Analytics diagnose why subscription ARR moved last week.
@Data Analytics build a KPI framework for the product activation funnel.
@Data Analytics analyze paid workspace retention and recommend what to investigate next.
```

For follow-up messages such as "yes", "walk me through it", "what happened?", or "show the steps" immediately after a completed guided workflow offers a walkthrough, answer from this index. Explain the observable steps, selected workflow, connector setup attempt, offline or demo-data fallback, clarifying questions, source gaps, and artifact assembly at a beginner-friendly level without revealing hidden reasoning.

### Broad Orientation And Help Requests

For broad orientation and help requests:

- Handle broad capability-summary asks from this index before choosing a focused workflow.
- Route pure capability-summary requests such as `what can you do?`, `show me the capabilities`, or `explain Data Analytics` here when the user wants orientation rather than a task choice.
- Route `what should I try?`, `what should I do?`, `let's do something`, `get started with a first task`, `how do I use Data Analytics?`, or `choose a guided workflow` through `Guided Flow And Source Setup`; route requests to save data context or create, update, inspect, or repair a semantic layer to `create-data-context`.
- Use this index-level help answer for capability summaries regardless of setup history; only explicit setup requests enter setup-specific handling.
- Answer from the skill map in this file using the default shape below.
- Keep the three generic examples below for capability and plugin-detail presentation. The two connected-source tasks plus `Upload your own`, or the no-source upload/sample fallback, belong only to structured first-task intake.
- Include a short setup context section only when the user asks about setup, available sources, Data Analytics configuration, or the current session already reveals a material source gap.
- Keep setup context analyst-facing: name the practical source, use model judgment to explain the likely user-experience impact from the source label, configured preferred routes, setup action, and suggested next prompts, then give the smallest next action or fallback.
- Show at most three highest-impact gaps by default, and never more than five setup-context bullets total. Prioritize gaps in the order most relevant to the examples you are suggesting rather than following a hard-coded impact catalog.
- If all sources are active, keep setup context to one sentence such as `Your core Data Analytics sources look ready; I'll still try each source only when a workflow needs it.`
- For setup context wording, be direct and practical, for example: `You won't be able to properly validate a metric from live tables until a warehouse or SQL source is available, but you can paste SQL, schema details, or exported query results for now.`
- Do not expose raw status names, connector ids, or implementation terms.
- Do not perform connector reads merely to answer a capability question; use current session app or tool availability already visible in context.

Use this default answer shape for broad orientation and help requests:

```md
Data Analytics can help with:
- Metric diagnostics and source-backed explanations for movement
- KPI design, metric definitions, and measurement frameworks
- Product and business analysis for funnels, retention, adoption, pricing, and strategic decisions
- KPI reports, dashboards, notebooks, and reusable semantic layers
- Market sizing, opportunity sizing, and decision-ready recommendations

Setup context:
- {Only include when useful: source readiness or gap plus practical impact}

Good first prompts:
- `@Data Analytics diagnose why subscription ARR moved last week.`
- `@Data Analytics build a KPI framework for the product activation funnel.`
- `@Data Analytics analyze paid workspace retention and recommend what to investigate next.`
```

# Plugin Purpose

Data Analytics turns connected or provided business data, source-of-truth context, dashboards, docs, chats, notebooks, spreadsheets, SQL, and semantic layers into source-backed analytical work products. It can define KPIs, diagnose metric movement, size markets, analyze product or business questions, validate data quality, gather context, build reproducible notebooks, design visualizations, create dashboards, produce polished reports, and convert those outputs into shareable Docs, Slides, spreadsheets, or other durable handoff surfaces.

## Semantic Layers

Semantic layers are source-backed local skills for product, business, metric, source, or reporting areas. They encode canonical metrics, tables, grains, joins, filters, query patterns, caveats, source precedence, and validation gaps.

Before answering questions about a named product area, metric, table, dashboard, SQL query, source choice, join, caveat, or recurring business question, use a semantic layer only when the user names a semantic layer or path, or a relevant semantic layer is already discoverable from the current runtime. If a relevant semantic layer exists, read it before selecting tables, writing SQL, reconciling dashboards, or giving metric definitions. Treat it as the domain-specific semantic map, then consult the connected or provided apps and verify high-stakes claims against the layer's cited sources.

When no relevant semantic layer exists and the user is asking a repeatable domain question, offer semantic-layer setup through `create-data-context`. Users can create multiple semantic layers for multiple product or business areas. Do not merge unrelated product areas into one broad layer unless the user explicitly asks for a cross-product semantic layer.

## Evidence And Handoff

Data Analytics plugin files use lane placeholders such as `~~structured_data` for whatever tool, connector, MCP server, plugin skill, pasted result, uploaded file, or schema description is available in that category. See [DEPENDENCIES.MD](../../DEPENDENCIES.MD) for provider options. When a required connector, plugin, MCP server, or source-of-truth lane is unavailable, follow the Source Access Guardrail. When an optional lane is unavailable, continue from pasted query results, uploaded files, SQL snippets, screenshots, schema descriptions, or other reviewed evidence and label the gap when it materially affects the answer.

Source rules:

- Gather source-of-truth context before writing SQL, notebook code, dashboards, reports, or conclusions.
- Prefer reproducible notebooks for fresh SQL, Python, statistics, modeling, source reconciliation, or non-trivial metric computation when a notebook materially improves auditability.
- Preserve relevant SQL, scripts, query permalinks, outputs, source links, and caveats in the final artifact or supporting notes.

Delivery surface boundary:

- Startup must work when the user does not want MCP widget or MCP artifact rendering. In that case, continue through the selected chat, notebook, SQL, HTML, BI, Streamlit, spreadsheet, slide, or other non-MCP surface and keep source notes in that surface's normal supporting artifacts.
- For report-mode work, `$build-report` owns MCP-versus-HTML selection. For other MCP widget or artifact surfaces, follow the selected surface's rules; before shaping widget/app-specific artifacts, read `../../src/analytics-app-core.md`.
- In `web_work_mode`, treat MCP UI rendering as unavailable by routing policy even when MCP UI tools are visible. This restriction does not prevent using MCP servers as data sources.
- Do not expose hidden reasoning, credentials, secrets, direct personal contact/payment identifiers, or unvalidated calculations in any user-facing surface. Reviewed customer, account, or company names may be included when they are needed for the analysis.
- Once the analysis commits to a source table in an inline or dashboard route, expose a small deterministic preview when safe through the selected surface's normal preview mechanism.
- If a preview is unsafe, unavailable, or blocked by access limits, record that briefly and continue from schema, documentation, or other reviewed evidence.

## Completion Gates

Report completion:

- The report run must choose exactly one report delivery mode through `$build-report`.
- Follow `$build-report`'s deterministic surface rule: Codex desktop defaults to `mcp-app`; positively identified web Work Mode uses `html`; desktop reaches `html` only for explicit user or downstream-conversion requirements, or after a concrete failed MCP attempt.
- Do not end with only an inline/chat summary or a localhost URL. Treat chat summaries as progress updates.
- If a required deliverable is skipped, include the explicit omission reason in the final handoff.
- HTML report charts must be Seaborn-generated PNG images.
- If the report includes charts, evidence tables, or custom visualizations, satisfy $visualize-data's chart contract and QA before embedding them.

Final review:

- Verify generated artifacts by opening, reading, rendering, or otherwise inspecting them.
- Check source-backed claims against the controlling sources used for the analysis.
- Call out unresolved gaps or caveats when they materially affect the conclusion.
- Verify that every selected primary workflow skill was read and followed. If a primary workflow was skipped, record why in the final handoff. Do not treat a semantic-layer lookup, notebook, validation pass, visualization, or report artifact as satisfying the primary workflow contract.
- If the run was classified as `report`, do not finalize until the downstream $build-report contract has either passed or been explicitly blocked.
- If a selected rendering surface is unsafe, unavailable, too large, or fails after a targeted retry, continue the analysis through another appropriate surface and briefly note the reason in the progress update or final handoff.

## Skills

### design-kpis

Use $design-kpis for goals, primary KPIs, driver metrics, guardrails, scorecards, measurement plans, and launch or experiment success criteria.

### kpi-reporting

Use $kpi-reporting for KPI updates, scorecards, business reviews, executive metric summaries, target or pacing readouts, and leadership-ready performance narratives. Add $metric-diagnostics when the update must explain why a KPI moved.

### market-sizing

Use $market-sizing for TAM/SAM/SOM, opportunity, spend or revenue pool, customer count, unit volume, commercial upside, and sensitivity models.

### metric-diagnostics

Use $metric-diagnostics to identify what drove a metric over a defined time period, baseline, or segment comparison, rule out measurement artifacts, label findings by certainty, and route the final report through $build-report.

### product-business-analysis

Use $product-business-analysis to analyze product or business data and context for recommendation-oriented decisions. Add $metric-diagnostics when the recommendation depends on validated metric movement.

### analyze-data-quality

Use $analyze-data-quality for freshness, grain, row counts, nulls, duplicates, schema drift, broken joins, outliers, backfills, and source or dashboard disagreement.

### build-dashboard

Use $build-dashboard for analytical dashboards, scorecards, monitoring pages, BI views, Streamlit dashboards, MCP artifact dashboards, BI platform dashboards, and dashboard QA.

### build-report

Use $build-report to build exactly one durable report surface selected for the user request, such as an MCP app report or an HTML report with Seaborn-generated PNG charts.

### report-to-google-doc

Use $report-to-google-doc to convert an existing local HTML report into a polished native Google Doc.

### report-to-google-slides

Use $report-to-google-slides to convert an existing local HTML report into a polished native Google Slides deck.

### report-to-pdf

Use $report-to-pdf to convert an existing static Data Analytics report export into a verified PDF artifact.

### gather-business-context

Use $gather-business-context for docs, dashboards, chats, planning notes, launch or experiment material, source-of-truth pages, owners, incidents, roadmap, GTM or customer context, and prior decisions.

### jupyter-notebooks

Use $jupyter-notebooks to create, edit, and verify reproducible notebooks for SQL, Python, statistics, modeling, cohort or funnel analysis, data-quality checks, experiments, market sizing, diagnostics, and report support.

### validate-data

Use $validate-data to QA methodology, source selection, SQL or query logic, calculations, visualization integrity, caveats, and whether conclusions are supported by evidence.

### visualize-data

Use $visualize-data to design, implement, and QA charts for reports, dashboards, decks, notebooks, scorecards, trends, decompositions, funnels, cohorts, distributions, uncertainty, and executive KPI readouts.

### create-data-context

Use `create-data-context` for semantic-layer setup and maintenance. Do not require saved data-context setup before ordinary Data Analytics work.
