import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

function sectionBetween(source, startHeading, endHeading) {
  const start = source.indexOf(startHeading);
  assert.notEqual(start, -1, `missing section start: ${startHeading}`);
  const end = source.indexOf(endHeading, start + startHeading.length);
  assert.notEqual(end, -1, `missing section end: ${endHeading}`);
  return source.slice(start, end);
}

function sectionFrom(source, startHeading) {
  const start = source.indexOf(startHeading);
  assert.notEqual(start, -1, `missing section start: ${startHeading}`);
  return source.slice(start);
}

test("plugin starter copy keeps guided flow separate from reusable context setup", () => {
  const manifest = JSON.parse(readFileSync(new URL("../.codex-plugin/plugin.json", import.meta.url), "utf8"));

  assert.match(manifest.description, /guide task-oriented data flows/);
  assert.ok(manifest.keywords.includes("guided-flow"));
  assert.match(manifest.interface.longDescription, /Guided flows help you choose and run task-oriented data work/);
  assert.doesNotMatch(manifest.interface.longDescription, /Guided onboarding helps|reusable data context/);
  assert.deepEqual(manifest.interface.defaultPrompt, [
    "Help me get started with my first data task",
    "Analyze product usage and recommend where the team should focus next",
    "Diagnose why a key metric changed and identify the biggest drivers",
  ]);
});

test("dependency copy stays tool agnostic about direct source access", () => {
  const dependencies = readFileSync(new URL("../DEPENDENCIES.MD", import.meta.url), "utf8");

  assert.match(dependencies, /Routes that can read the needed source directly usually give the best experience/);
  assert.match(dependencies, /including native connectors, custom MCP servers, and other callable tools/);
  assert.doesNotMatch(dependencies, /Direct connectors give the best experience/);
});

test("guided intake uses two connector tasks plus upload your own or upload and sample fallbacks", () => {
  const index = readFileSync(new URL("../skills/index/SKILL.md", import.meta.url), "utf8");
  const guided = sectionBetween(index, "### Guided Flow And Source Setup", "### Source Discovery And Verification");
  const intake = sectionBetween(guided, "#### First-task intake", "#### Selection handling");
  const selection = sectionBetween(guided, "#### Selection handling", "#### Custom-question access");
  const options = sectionBetween(guided, "#### Connected-source option copy", "#### Demo data");
  const connectedForm = sectionBetween(intake, "Connected-source form:", "No-source form:");
  const noSourceForm = sectionFrom(intake, "No-source form:");

  assert.match(guided, /owns task selection, setup-adjacent routing, and guided workflow continuation/);
  assert.match(guided, /stateless first-task flow/);
  assert.match(guided, /If the user already supplied a concrete task, skip intake and treat it as a custom question/);
  assert.match(guided, /Never ask where to find data or show a source, project, dashboard, table, SQL, file, connector, or provider picker/);
  assert.match(guided, /Do not create saved data context from this flow/);

  assert.match(intake, /runtime-provided installed Apps and Plugins inventory plus callable tools already visible/);
  assert.match(intake, /including custom MCP servers and other callable tools that can read the needed source/);
  assert.match(intake, /Do not read connector records, call `functions\.list_available_plugins_to_install`, or treat `.app\.json` and \[DEPENDENCIES\.MD\]/);
  assert.match(intake, /use `tool_search` by the name, source type, or task-relevant capability/);
  assert.match(intake, /already-visible or user-named connector, custom MCP server, or other callable tool/);
  assert.match(intake, /do not search only a fixed provider catalog/);
  assert.match(intake, /exactly three options: two distinct tasks backed by existing installed connectors or callable tools, followed by `Upload your own`/);
  assert.match(intake, /if fewer than two are useful, derive multiple non-duplicative tasks from the same connected source's capabilities/);
  assert.match(intake, /Never include sample, installation, or unsupported options/);
  assert.match(intake, /offer exactly `Upload data` followed by `Use sample data`/);
  assert.match(intake, /Do not add `Connect a data source`/);

  for (const label of ["{connected task 1}", "{connected task 2}"]) {
    assert.ok(connectedForm.includes(`label: "${label}"`), `missing connected option ${label}`);
  }
  assert.match(connectedForm, /label: "Upload your own"/);
  assert.match(connectedForm, /Upload or paste your own data and produce an analytics report with findings and next steps/);
  assert.doesNotMatch(connectedForm, /\{connected task 3\}|Upload data|Use sample data|Connect a data source/);
  assert.match(noSourceForm, /label: "Upload data"/);
  assert.match(noSourceForm, /label: "Use sample data"/);
  assert.doesNotMatch(noSourceForm, /Connect a data source/);

  assert.match(intake, /Use `Dashboard`, `Report`, or `Data task` as the header/);
  assert.match(intake, /What should the dashboard be about\?/);
  assert.match(intake, /What should the report be about\?/);
  assert.match(intake, /The Data Analytics plugin helps Codex turn data into insights, recommendations, and decision-ready artifacts\. Try it out with one of these prompts:/);
  assert.match(intake, /built-in free-form Other field for a custom question/);
  assert.doesNotMatch(intake, /\(Recommended\)/);

  assert.match(selection, /Connected-source task: use its existing connector or callable tool/);
  assert.match(selection, /do not open plugin installation/);
  assert.match(selection, /`Upload your own` or `Upload data`: ask for the smallest useful export/);
  assert.match(selection, /`Use sample data`: start the demo contract immediately/);
  assert.match(selection, /Other text: treat it as a user-authored custom question/);

  assert.match(options, /warehouse\/source system first, then BI, product analytics, GitHub, tabular Drive\/files/);
  assert.match(options, /If one connector fills multiple slots, vary the task by real connector capability/);
  for (const label of [
    "Analyze business data",
    "Analyze dashboard trends",
    "Analyze product usage",
    "Analyze GitHub activity",
    "Analyze email trends",
    "Analyze Drive files",
    "Analyze meeting patterns",
    "Analyze Notion content",
    "Analyze Slack activity",
    "Analyze Teams messages",
    "Analyze SharePoint files",
  ]) {
    assert.ok(options.includes(`\`${label}\``), `missing option copy for ${label}`);
  }
});

test("only user-authored custom questions can trigger connector installation", () => {
  const index = readFileSync(new URL("../skills/index/SKILL.md", import.meta.url), "utf8");
  const guided = sectionBetween(index, "### Guided Flow And Source Setup", "### Source Discovery And Verification");
  const access = sectionBetween(guided, "#### Custom-question access", "#### Connected-source option copy");

  assert.match(access, /Only a concrete task supplied in the user's message or the intake form's Other field may trigger installation/);
  assert.match(access, /custom MCP server, other callable tool, uploaded or pasted artifact/);
  assert.match(access, /check visible or lazy-loadable custom MCP servers and other callable tools that can read the needed source before native connector installation/);
  assert.match(access, /server or tool name, description, action schema, or the user-named source/);
  assert.match(access, /routing hints, not the source universe/);
  assert.match(access, /call `functions\.list_available_plugins_to_install` once/);
  assert.match(access, /current-run context already lists exact suppressed plugin-install ids/);
  assert.match(access, /do not run the legacy preflight just to obtain suppressions/);
  assert.match(access, /call `functions\.request_plugin_install` sequentially for every exact returned candidate useful to the task/);
  assert.match(access, /Do not guess ids, narrow to one generic "best" candidate, stop after the first useful candidate, call installs in parallel, or use `request_connector_setup`/);
  assert.match(access, /record that exact id with `record_plugin_install_suppression\.py`/);

  assert.match(access, /Warehouse exception/);
  assert.match(access, /keep every returned warehouse candidate/);
  assert.match(access, /Ask which warehouse to use, naming all of them; install only the selected exact candidate/);
  assert.match(access, /Never choose by manifest order or configured preference/);

  assert.match(access, /id: "fallback_next_step"/);
  assert.match(access, /question: "I don't have enough data to complete this task\. How do you want to proceed\?"/);
  assert.match(access, /header: "Next step"/);
  assert.match(access, /label: "Upload data"/);
  assert.match(access, /label: "Use sample data"/);
  assert.match(access, /After successful setup, start the focused workflow automatically/);
  assert.match(access, /Do not show post-setup flow-control choices/);
});

test("missing data always closes with upload or synthetic demo choices", () => {
  const index = readFileSync(new URL("../skills/index/SKILL.md", import.meta.url), "utf8");
  const guided = sectionBetween(index, "### Guided Flow And Source Setup", "### Source Discovery And Verification");
  const invariant = sectionBetween(guided, "#### No-source completion invariant", "#### Connected-source option copy");
  const guardrail = sectionBetween(index, "### Source Access Guardrail", "### Audience And Language");

  assert.match(invariant, /MUST offer `Upload data` and `Use sample data` before the turn ends/);
  assert.match(invariant, /install prompt being declined, dismissed, canceled, or left unconfirmed/);
  assert.match(invariant, /successful install that still cannot return usable evidence/);
  assert.match(invariant, /Do not end with only a missing-source explanation, an installation suggestion, or an instruction to connect a source and retry/);
  assert.match(invariant, /installation prompt may come before the fallback question, but it never replaces the fallback question/);
  assert.match(invariant, /bundled demo is synthetic and will demonstrate the workflow rather than answer the user's real-data question/);

  assert.match(guardrail, /apply the mandatory `No-source completion invariant`/);
  assert.match(guardrail, /offer uploaded data or the clearly labeled synthetic demo before ending the same turn/);
});

test("demo contract uses the bundled synthetic dataset", () => {
  const index = readFileSync(new URL("../skills/index/SKILL.md", import.meta.url), "utf8");
  const demoSection = sectionBetween(index, "#### Demo data", "### Source Discovery And Verification");
  const demo = readFileSync(new URL("../assets/demo-product-growth.csv", import.meta.url), "utf8")
    .trim()
    .split(/\r?\n/);

  assert.match(demoSection, /Show `Use sample data` only when no useful connected source exists or a selected workflow still lacks usable evidence/);
  assert.match(demoSection, /\[demo-product-growth\.csv\]\(\.\.\/\.\.\/assets\/demo-product-growth\.csv\)/);
  assert.match(demoSection, /label it synthetic/);
  assert.match(demoSection, /analyze it with reproducible SQL without inventing rows or findings/);
  assert.equal(demo[0], "week_start,acquisition_channel,signups,activated_users,paid_conversions,revenue_usd,support_tickets");
  assert.equal(demo.length - 1, 32);
  assert.ok(demo.slice(1).every((row) => row.split(",").length === 7));
});

test("Data Analytics uses global guided-flow input without an intake MCP server", () => {
  const mcpConfig = JSON.parse(readFileSync(new URL("../.mcp.json", import.meta.url), "utf8"));

  assert.equal(mcpConfig.mcpServers?.dataAnalyticsIntake, undefined);
  assert.equal(mcpConfig.mcpServers?.datascienceIntake, undefined);
  assert.ok(mcpConfig.mcpServers?.dataAnalyticsWidgets);
  assert.equal(mcpConfig.mcpServers.dataAnalyticsWidgets.title, "Data Analytics");
  assert.equal(existsSync(new URL("../mcp/intake-server.mjs", import.meta.url)), false);
});

test("guided flow remains separate from create-data-context setup", () => {
  const index = readFileSync(new URL("../skills/index/SKILL.md", import.meta.url), "utf8");
  const dataContext = readFileSync(new URL("../skills/create-data-context/SKILL.md", import.meta.url), "utf8");
  const guided = sectionBetween(index, "### Guided Flow And Source Setup", "### Source Discovery And Verification");

  assert.doesNotMatch(guided, /semantic|future data work|reusable semantic layer/i);
  assert.match(dataContext, /name: create-data-context/);
  assert.match(dataContext, /Data-task routing is owned by the Data Analytics `index` skill/);
  assert.match(dataContext, /Use this skill only when the user asks to save data context or create, update, inspect, or repair a semantic layer/);
  assert.doesNotMatch(dataContext, /Route to data task|What should Data Analytics set up/);
});

test("standalone guided-flow skill is absent", () => {
  assert.equal(existsSync(new URL("../skills/guided-flow", import.meta.url)), false);
  assert.equal(existsSync(new URL("../skills/onboarding", import.meta.url)), false);
  assert.equal(existsSync(new URL("../skills/user-context", import.meta.url)), false);
});
