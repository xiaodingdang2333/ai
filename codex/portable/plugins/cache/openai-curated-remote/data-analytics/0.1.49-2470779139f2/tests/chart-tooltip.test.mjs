import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("tooltip percent encodings inherit chart percent semantics for literal percent units", async () => {
  const source = await readFile(new URL("../src/analytics-app/charting/ChartTooltip.tsx", import.meta.url), "utf8");

  assert.match(source, /function tooltipEncodingValueFormat\(chart: ChartSpec, encoding: ChartEncodingSpec\): ValueFormat/);
  assert.match(source, /chart\.valueFormat === "percent" && isPercentSymbolUnit\(encoding\.unit\)/);
  assert.match(source, /formatValue\(item\.value, valueFormat, encoding\.unit\)/);
});
