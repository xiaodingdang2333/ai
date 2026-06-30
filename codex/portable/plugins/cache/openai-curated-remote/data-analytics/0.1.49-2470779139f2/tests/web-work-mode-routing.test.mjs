import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

test("preserves desktop data-context and MCP UI capabilities", () => {
  for (const relativePath of [
    "../.mcp.json",
    "../mcp/server.cjs",
    "../src/analytics-app/App.tsx",
    "../skills/create-data-context/SKILL.md",
    "../skills/build-dashboard/specifications/mcp-artifact-dashboard.md",
    "../skills/build-report/specifications/mcp-app-report.md",
  ]) {
    assert.equal(existsSync(new URL(relativePath, import.meta.url)), true, relativePath);
  }
});

test("classifies surface and mode independently from positive signals", () => {
  const index = read("../skills/index/SKILL.md");

  assert.match(index, /Classify `surface` and `mode` separately/);
  assert.match(index, /`surface = codex_desktop`/);
  assert.match(index, /`surface = chatgpt_web`/);
  assert.match(index, /`mode = work_mode`/);
  assert.match(index, /`mode = chat`/);
  assert.match(index, /Never infer mode from surface, missing tools, tool failure/);
  assert.match(index, /only when `surface = chatgpt_web` and `mode = work_mode` are both positively identified/);
});

test("web Work Mode uses conversational intake without structured forms", () => {
  const index = read("../skills/index/SKILL.md");

  assert.match(index, /Do not use structured intake or call `request_user_input`/);
  assert.match(index, /Use the structured form contract below only when `surface = codex_desktop`/);
  assert.match(index, /In `chatgpt_web`, `work_mode`, or an unknown environment, do not emit a structured form or schema/);
  assert.match(index, /present the same task or fallback choices compactly in normal conversation/);
});

test("web Work Mode keeps data context current-session only", () => {
  const index = read("../skills/index/SKILL.md");
  const dataContext = read("../skills/create-data-context/SKILL.md");

  assert.match(index, /Do not route to `create-data-context` or create, update, or repair a semantic-layer artifact/);
  assert.match(index, /keep the context current-session only/);
  assert.match(dataContext, /do not start semantic-layer creation, update, inspection, repair, local skill writing, or recurring refresh setup/);
  assert.match(dataContext, /Outside positively identified web Work Mode, keep this skill's existing behavior unchanged/);
});

test("web Work Mode avoids MCP UI while retaining MCP data sources", () => {
  const index = read("../skills/index/SKILL.md");
  const dashboard = read("../skills/build-dashboard/SKILL.md");
  const report = read("../skills/build-report/SKILL.md");
  const visualize = read("../skills/visualize-data/SKILL.md");
  const dashboardSpec = read("../skills/build-dashboard/specifications/mcp-artifact-dashboard.md");
  const reportSpec = read("../skills/build-report/specifications/mcp-app-report.md");

  assert.match(index, /Do not select Data Analytics MCP UI surfaces/);
  assert.match(index, /MCP servers and other callable tools remain valid data sources/);
  assert.match(dashboard, /do not select the Data Analytics MCP artifact app/);
  assert.match(dashboard, /otherwise build portable HTML/);
  assert.match(report, /ChatGPT web Work Mode: use `html`/);
  assert.match(visualize, /use native Work Mode chart or table rendering when available/);
  assert.match(dashboardSpec, /Do not select this specification when `surface = chatgpt_web` and `mode = work_mode`/);
  assert.match(reportSpec, /Do not select this specification when `surface = chatgpt_web` and `mode = work_mode`/);
});

test("desktop reports default to MCP and require a concrete HTML fallback", () => {
  const index = read("../skills/index/SKILL.md");
  const report = read("../skills/build-report/SKILL.md");

  assert.match(report, /Codex desktop: use `mcp-app` by default/);
  assert.match(report, /ChatGPT web Work Mode: use `html`/);
  assert.match(report, /On Codex desktop, use `html` only when the user explicitly asks/);
  assert.match(report, /an MCP app report was actually attempted and failed/);
  assert.match(index, /Codex desktop defaults to `mcp-app`/);
  assert.match(index, /after a concrete failed MCP attempt/);
});
