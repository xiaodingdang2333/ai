---
name: fanqie-novel-ideation
description: Generate and shortlist original, commercially viable Fanqie/Tomato web-novel concepts with a mandatory 12-to-3 funnel, local ranking-function analysis, genre-promise checks, anti-cliche transformation, and scored review. Use when the user asks to start, brainstorm, create, position, name, or plan a future new Fanqie/web novel, or says current ideas feel stale or cliched. Do not use for continuing an existing book.
---

# Fanqie Novel Ideation

## Purpose

Run a gated ideation process before any future new Fanqie book is created. Produce twelve genuinely different concepts, score them, retain three, and stop for the user's selection. Existing books and their continuations are exempt.

## Non-Negotiable Gate

For a future new book:

1. Complete the `12 -> 3` funnel.
2. Present the three finalists and their risks.
3. Stop. Do not create a novel folder, book record, outline, chapters, drafts, or uploads.
4. Continue only after the user explicitly selects one finalist.
5. After selection, create the project and write exactly three trial chapters for review. Do not bulk-write or upload until the user approves the trial.

If the user is continuing an existing book, hand off directly to `fanqie-write-upload`.

## Required Inputs

Infer reasonable defaults from the conversation and shared memory. Establish:

- target readers and channel;
- primary category and optional secondary category;
- the exact emotional promise in one sentence;
- desired reading load and tone;
- explicit dislikes and recently repeated structures.

For book-creation tags, read `/home/admin/ai/memory/fanqie-book-creation-tags.md`. For durable preferences, read `/home/admin/ai/memory/workflow-preferences.md`.

## Source Boundaries

Use local ranking samples under `/home/admin/ai/txt/排行榜/番茄排行榜/` only as market evidence. Extract functions such as:

- opening-hook speed;
- emotional promise and payoff frequency;
- relationship progression;
- unit and chapter pacing;
- title and synopsis clarity.

Never reuse or closely transform a sample's names, signature events, relationship configuration, world sequence, wording, or title syntax as a whole. Record only abstract functional DNA. Use `dna-extraction` and `adaptation-synthesis` function-first principles.

## Phase 1: Baseline And Prohibitions

1. Read a small relevant sample set, normally 3-6 books. Do not scan the whole corpus without need.
   - Choose current candidates from the official Fanqie category ranking when live ranking access is available.
   - Use `/home/admin/ai/scripts/sonovel.sh packet '<书名>' '<官方作者>'` to build a local selected-chapter packet when the book is downloadable.
   - A mirror author of `佚名` or a smaller mirror chapter count is not an automatic mismatch. Confirm the book through its synopsis or first chapter titles.
   - If the exact book cannot be found or cannot be confirmed, skip it and continue with the next ranked book. Do not spend repeated retries on one title.
2. Use `genre-conventions` to define the primary reader promise. A secondary genre may support it but must not take over.
3. List first-thought cliches and the user's prohibited patterns.
4. Identify why each cliche exists, then preserve its useful function through a different form using `cliche-transcendence`.
5. Save `01_市场基线与禁用套路.md` using [references/output-template.md](references/output-template.md).

For light romantic quick transmigration, default prohibitions include fake-heiress repetition, substitute-bride repetition, internet-wide public trials, evidence-chain investigations, dense timelines, and a male lead whose affection appears only as procedural help. These can be used only after substantial structural transformation and only if the user asks for them.

## Phase 2: Generate Exactly Twelve

Use `story-idea-generator` to create exactly twelve concepts. The emotional experience comes first; settings serve it. Apply `statistical-distance`: keep enough category familiarity for immediate comprehension while moving two or three load-bearing elements away from the statistical center.

The twelve must vary across all these dimensions:

- world rule or trans-world mechanism;
- relationship structure;
- professional or social ecology;
- heroine identity and agency;
- ability, privilege, or protection cost;
- source of serial conflict.

Use `list-builder` principles to fill dimensional gaps. Do not submit the same plot with different eras, professions, or character names. Each idea must include a one-line hook, emotional payoff mechanism, heroine action engine, relationship engine, serialization engine, and major risk.

Save all candidates to `02_十二个创意候选.md`.

## Phase 3: Score And Reject

Score each concept with [references/scoring-rubric.md](references/scoring-rubric.md):

- originality: 25;
- emotional-promise fit: 20;
- opening hook: 15;
- serialization fertility: 15;
- heroine agency: 10;
- romantic chemistry: 10;
- Fanqie fit: 5.

Hard rejection rules:

- total below 75;
- originality below 18;
- emotional-promise fit below 16;
- concept breaks the stated dislike/prohibition list;
- concept requires detective-style explanation to understand the romance;
- concept cannot sustain at least five materially different story units.

Rejected ideas remain visible with rejection reasons. Do not inflate scores to force three survivors; revise or replace weak candidates until at least three legitimately pass.

## Phase 4: Select Three And Stop

Rank the eligible ideas and select three that are strong individually and different from one another. Before finalizing:

1. Search local project titles and ranking filenames for close collisions.
2. Search the public web for exact or near-exact title collisions when candidate titles are proposed.
3. Rename titles that look derivative, confusingly similar, or too close to an existing project.
4. Compare the three against each other for mechanism and emotional-payoff duplication.

Save `03_三强评审.md`. Present each finalist with score, hook, why it can retain readers, likely weakness, and a concrete mitigation. Ask the user to select one. Do not recommend all three as equally good.

## Phase 5: After User Selection

Only after explicit selection:

1. Create the novel project and creation information.
2. Produce cover support according to shared memory.
3. Build a minimum viable world/relationship outline.
4. Use `fanqie-write-upload` writing rules to write three trial chapters, each at least 2500 Chinese characters and normally about 3000.
5. Run local QA and return the trial for approval.
6. Bulk writing and draft upload require a later explicit approval.

## Output Location

Use this fixed path without asking:

`/home/admin/ai/txt/创意池/<YYYY-MM-DD>-<题材>/`

Required files:

- `01_市场基线与禁用套路.md`
- `02_十二个创意候选.md`
- `03_三强评审.md`

These are ideation artifacts, not a novel project. Do not create `正文/`, `大纲/`, or a Fanqie work ID during the funnel.

## Quality Test

The funnel passes only when:

- all twelve are structurally distinct, not costume swaps;
- the primary emotional promise is visible in the opening premise and recurring payoff;
- the heroine causes plot movement rather than merely receiving protection;
- affection is shown through repeated choices, priority, and cost, not only claims or evidence gathering;
- the premise is explainable in two sentences;
- each finalist has enough variation for long serialization without repeating one emotional beat.
