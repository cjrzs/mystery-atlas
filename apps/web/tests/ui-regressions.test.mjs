import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectRoot = new URL("../../../", import.meta.url);

async function source(relativePath) {
  return readFile(new URL(relativePath, projectRoot), "utf8");
}

test("browser API calls stay on the web origin", async () => {
  const apiSource = await source("apps/web/src/lib/api.ts");
  const nextConfig = await source("apps/web/next.config.ts");

  assert.match(apiSource, /export const API_BASE = ["']\/api\/v1["'];/);
  assert.match(nextConfig, /source:\s*["']\/api\/v1\/:path\*["']/);
  assert.match(nextConfig, /destination:\s*`\$\{apiOrigin\}\/api\/v1\/:path\*`/);
});

test("the running web app proxies API requests", async () => {
  const response = await fetch("http://127.0.0.1:3100/api/v1/works");

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /application\/json/);
});

test("development-only UI is hidden and extension attributes do not warn", async () => {
  const nextConfig = await source("apps/web/next.config.ts");
  const layout = await source("apps/web/src/app/layout.tsx");

  assert.match(nextConfig, /devIndicators:\s*false/);
  assert.match(layout, /<html lang="zh-CN" suppressHydrationWarning>/);
});

test("archive controls share one responsive toolbar row", async () => {
  const archiveBrowser = await source("apps/web/src/components/archive-browser.tsx");
  const styles = await source("apps/web/src/app/globals.css");

  assert.match(archiveBrowser, /className="archive-toolbar-row"/);
  assert.match(styles, /\.archive-toolbar-row\s*\{[\s\S]*display:\s*flex/);
  assert.match(styles, /\.archive-search\s*\{[\s\S]*flex:\s*1/);
});

test("private library failures are scoped to the private tab", async () => {
  const archiveBrowser = await source("apps/web/src/components/archive-browser.tsx");

  assert.doesNotMatch(archiveBrowser, /setLoadError\([^)]*私人档案失败/);
  assert.match(archiveBrowser, /privateLoadError/);
  assert.match(archiveBrowser, /retryPrivateLibrary/);
});

test("public demo works appear only as an API failure fallback", async () => {
  const archiveBrowser = await source("apps/web/src/components/archive-browser.tsx");

  assert.match(archiveBrowser, /useState<ArchiveWork\[]>\(\[\]\)/);
  assert.match(archiveBrowser, /publicLoading/);
  assert.match(
    archiveBrowser,
    /\.catch\(\(\) => \{[\s\S]*setPublicWorks\(fallbackWorks\)/,
  );
});

test("private archives expose book-tag filters", async () => {
  const archiveBrowser = await source("apps/web/src/components/archive-browser.tsx");
  const apiTypes = await source("apps/web/src/lib/api.ts");

  assert.match(apiTypes, /tags:\s*string\[]/);
  assert.match(archiveBrowser, /privateItems\.flatMap\(\(item\) => item\.tags\)/);
  assert.match(archiveBrowser, /activePrivateFilter/);
  assert.match(archiveBrowser, /item\.tags\.includes\(activePrivateFilter\)/);
  assert.match(archiveBrowser, /scope === "private"[\s\S]*privateFilters\.map/);
  assert.doesNotMatch(archiveBrowser, /value:\s*"private_upload"/);
});

test("import confirmation only asks for archive type after AI metadata preparse", async () => {
  const importPage = await source("apps/web/src/app/library/import/page.tsx");
  const apiTypes = await source("apps/web/src/lib/api.ts");

  assert.match(apiTypes, /detected_tags:\s*string\[]/);
  assert.match(importPage, /AI 预解析结果/);
  assert.match(importPage, /封面、序章或目录/);
  assert.match(importPage, /item\.detected_tags\.join\("、"\)/);
  assert.match(importPage, /key=\{`\$\{item\.id\}:\$\{item\.stage\}`\}/);
  assert.doesNotMatch(importPage, /setTitle|setAuthor|setPublisher|setTranslator|setIsbn/);
  assert.match(
    importPage,
    /JSON\.stringify\(\{\s*visibility,\s*rights_confirmed:\s*visibility === "public",\s*\}\)/,
  );
});

test("low-confidence EPUB structure can be reviewed without losing source blocks", async () => {
  const importPage = await source("apps/web/src/app/library/import/page.tsx");
  const apiTypes = await source("apps/web/src/lib/api.ts");

  assert.match(apiTypes, /structure_requires_review:\s*boolean/);
  assert.match(apiTypes, /blocks\?:\s*ReaderBlock\[]/);
  assert.match(importPage, /请复核章节结构/);
  assert.match(importPage, /并入上一章/);
  assert.match(importPage, /从“\{heading\.title\}”处分拆/);
  assert.match(importPage, /`\/imports\/\$\{item\.id\}\/structure`/);
  assert.match(importPage, /method:\s*"PUT"/);
  assert.match(importPage, /保存结构并继续/);
});

test("workbench analysis consoles use the selected book instead of demo fixtures", async () => {
  const workbench = await source("apps/web/src/components/workbench.tsx");
  const apiTypes = await source("apps/web/src/lib/api.ts");

  assert.doesNotMatch(workbench, /from ["']@\/lib\/demo-data["']/);
  assert.match(workbench, /`\/library\/\$\{libraryItemId\}`/);
  assert.match(workbench, /`\/works\/\$\{slug\}`/);
  assert.match(workbench, /\/analysis\?through_chapter=\$\{chapter\}/);
  assert.match(apiTypes, /job_id:\s*string\s*\|\s*null/);
  assert.match(apiTypes, /can_manage_retry:\s*boolean/);
  assert.match(apiTypes, /can_retry:\s*boolean/);
  assert.match(apiTypes, /can_restart:\s*boolean/);
  assert.match(apiTypes, /retry_hint:\s*string/);
  assert.match(workbench, /`\/analysis-jobs\/\$\{analysis\.job_id\}\/retry`/);
  assert.match(workbench, /analysis\?\.can_manage_retry/);
  assert.match(workbench, /重新分析/);
  const retryHandler = workbench.slice(
    workbench.indexOf("const retryAnalysis"),
    workbench.indexOf("const backHref"),
  );
  assert.doesNotMatch(retryHandler, /window\.confirm/);
  assert.doesNotMatch(workbench, /重试失败阶段/);
  assert.doesNotMatch(workbench, /从头重新分析/);
  assert.match(workbench, /analysis\?\.retry_hint/);
  assert.match(
    workbench,
    /analysis\.status === "running" \|\| analysis\.status === "failed"/,
  );
  assert.doesNotMatch(workbench, /\/retry-stage/);
  assert.doesNotMatch(workbench, /\/restart/);
  assert.doesNotMatch(workbench, /\/analysis\/retry/);
  assert.doesNotMatch(workbench, /雾港钟楼|第二枚钟锤|沈砚|顾青禾/);
});

test("workbench does not log backend failures in the browser console", async () => {
  const workbench = await source("apps/web/src/components/workbench.tsx");
  const apiSource = await source("apps/web/src/lib/api.ts");

  assert.doesNotMatch(workbench, /console\.(?:error|warn|log)/);
  assert.doesNotMatch(apiSource, /console\.(?:error|warn|log)/);
});

test("reader preserves semantic blocks and exposes focus preferences", async () => {
  const workbench = await source("apps/web/src/components/workbench.tsx");
  const styles = await source("apps/web/src/app/globals.css");
  const apiTypes = await source("apps/web/src/lib/api.ts");

  assert.match(apiTypes, /type ReaderBlock/);
  assert.match(workbench, /ReaderBlockContent/);
  assert.match(workbench, /ReaderSettings/);
  assert.match(workbench, /readerFocused/);
  assert.match(workbench, /\/auth\/reader-preferences/);
  assert.match(styles, /\.workbench-grid\.reader-focused/);
  assert.match(styles, /text-indent:\s*2em/);
  assert.match(styles, /--reader-content-width/);
});

test("reader exposes a chapter directory and resets scroll after chapter changes", async () => {
  const workbench = await source("apps/web/src/components/workbench.tsx");
  const styles = await source("apps/web/src/app/globals.css");

  assert.match(workbench, /readerTocOpen/);
  assert.match(workbench, /aria-label="目录"/);
  assert.match(workbench, /readerBook\?\.chapters\.map/);
  assert.match(workbench, /ref=\{readerCopyRef\}/);
  assert.match(
    workbench,
    /readerCopyRef\.current\?\.scrollTo\(\{[\s\S]*top:\s*0/,
  );
  assert.match(workbench, /structural_path:\s*item\.structural_path\s*\?\?\s*\[\]/);
  assert.match(styles, /\.reader-toc\s*\{/);
  assert.match(
    styles,
    /\.reader-toc-list button\s*\{[^}]*grid-template-columns:\s*minmax\(80px, 38%\) minmax\(0, 1fr\)/,
  );
  assert.match(
    styles,
    /\.reader-toc-list button span\s*\{[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/,
  );
});

test("character graph is organized around structural core people", async () => {
  const graph = await source("apps/web/src/components/character-graph.tsx");

  assert.doesNotMatch(graph, /name:\s*["']circle["']/);
  assert.match(graph, /coreNodeIds/);
  assert.match(graph, /name:\s*["']cose["']/);
});

test("character graph system labels are normalized and displayed in Chinese", async () => {
  const graph = await source("apps/web/src/components/character-graph.tsx");
  const labels = await source("apps/web/src/lib/graph-labels.ts");
  const workbench = await source("apps/web/src/components/workbench.tsx");

  assert.match(labels, /professional:\s*"职业"/);
  assert.match(labels, /unknown:\s*"其他关系"/);
  assert.match(labels, /confirmed:\s*"已确认"/);
  assert.match(graph, /relationCategory\(edge\.kind\)/);
  assert.match(workbench, /relationKindGroups/);
  assert.match(workbench, /relationKindName\(category\)/);
  assert.doesNotMatch(workbench, /relationKindNames\[kind\]\s*\?\?\s*kind/);
});

test("workbench console text is larger without overriding reader copy preferences", async () => {
  const graph = await source("apps/web/src/components/character-graph.tsx");
  const styles = await source("apps/web/src/app/globals.css");

  assert.match(graph, /"font-size":\s*14/);
  assert.match(graph, /"font-size":\s*12/);
  assert.match(styles, /\.relation-filters button\s*\{[\s\S]*font-size:\s*11px/);
  assert.match(styles, /\.workbench-analysis-status small\s*\{[\s\S]*font-size:\s*11px/);
  assert.match(styles, /\.reader-copy p\s*\{[\s\S]*font-size:\s*var\(--reader-font-size\)/);
});
