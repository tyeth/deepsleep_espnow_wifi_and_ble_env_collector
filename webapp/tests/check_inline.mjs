// Static check: extract every inline <script> block from index.html and run `node --check`
// on it (plus the standalone scripts). Run: node webapp/tests/check_inline.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)([^>]*)>([\s\S]*?)<\/script>/g)];
for (const [,attrs,code] of scripts) if (/type="importmap"/.test(attrs)) JSON.parse(code);
const blocks = scripts.filter(m => !/type="importmap"/.test(m[1])).map(m => m[2]);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "envhub-check-"));
let n = 0;
for (const [i, code] of blocks.entries()) {
  const f = path.join(tmp, `inline_${i}.js`);
  fs.writeFileSync(f, code);
  execFileSync(process.execPath, ["--check", f], {stdio: "inherit"});
  n++;
}
for (const f of ["ai_tools.js", "prompt_backend.js", "webmcp.js", "sw.js"]) {
  execFileSync(process.execPath, ["--check", path.join(root, f)], {stdio: "inherit"});
  n++;
}
console.log(`syntax OK: ${blocks.length} inline block(s), ${n} files total`);
