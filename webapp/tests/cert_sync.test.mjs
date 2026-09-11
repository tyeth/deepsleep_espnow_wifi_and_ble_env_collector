// Tests the cert-sync helpers in index.html: the PEM validation that guards what
// gets pushed to the hub, and the CORS-proxy fallback. The helpers are marked off
// in the page so they can be evaluated here without a DOM.
// Run: node webapp/tests/cert_sync.test.mjs
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const m = html.match(/\/\* --- cert helpers:[\s\S]*?\n([\s\S]*?)\/\* --- end cert helpers --- \*\//);
assert.ok(m, "cert helper block not found in index.html (markers moved?)");

// Evaluate the block and hand back the names under test.
const load = (fetchImpl) => {
  const fn = new Function("fetch", "AbortSignal",
    `${m[1]}\nreturn {fetchViaCors,fetchCertFile,pemChain,validateCertPair,certFileKind,CERT_SRC,CERT_COMBINED,CERT_KEY};`);
  return fn(fetchImpl, { timeout: () => undefined });
};
const H = load(async () => { throw new Error("no fetch in this test"); });

const LEAF = "-----BEGIN CERTIFICATE-----\nleaf\n-----END CERTIFICATE-----";
const INTER = "-----BEGIN CERTIFICATE-----\ninter\n-----END CERTIFICATE-----";
const ROOT = "-----BEGIN CERTIFICATE-----\nroot\n-----END CERTIFICATE-----";
const KEY = "-----BEGIN PRIVATE KEY-----\nkkk\n-----END PRIVATE KEY-----";

let groups = 0;
const group = (name, fn) => { fn(); groups++; console.log("ok -", name); };
const rejects = async (p, re) => {
  try { await p; assert.fail("expected a rejection"); }
  catch (e) { assert.match(String(e.message || e), re); }
};

group("pemChain keeps leaf + intermediate and drops the root", () => {
  const out = H.pemChain([LEAF, INTER, ROOT].join("\n"));
  assert.equal((out.match(/BEGIN CERTIFICATE/g) || []).length, 2);
  assert.ok(out.includes("leaf") && out.includes("inter") && !out.includes("root"));
  assert.equal(H.pemChain(""), "\n");
});

group("validateCertPair accepts a real pair and returns the trimmed chain", () => {
  const { chain, key } = H.validateCertPair([LEAF, INTER, ROOT].join("\n"), KEY);
  assert.equal((chain.match(/BEGIN CERTIFICATE/g) || []).length, 2);
  assert.equal(key, KEY);
});

group("validateCertPair rejects a short chain, a missing key and an HTML error page", () => {
  assert.throws(() => H.validateCertPair(LEAF, KEY), /expected leaf \+ intermediate, found 1/);
  assert.throws(() => H.validateCertPair([LEAF, INTER].join("\n"), "nope"), /no PRIVATE KEY block/);
  // what a CORS proxy or captive portal hands back with status 200
  assert.throws(() => H.validateCertPair("<html>403 Forbidden</html>", KEY), /found 0/);
  assert.throws(() => H.validateCertPair(undefined, undefined), /found 0/);
});

group("validateCertPair accepts RSA and EC key headers", () => {
  for (const k of ["RSA PRIVATE KEY", "EC PRIVATE KEY", "PRIVATE KEY"])
    assert.ok(H.validateCertPair([LEAF, INTER].join("\n"),
      `-----BEGIN ${k}-----\nx\n-----END ${k}-----`));
});

group("certFileKind tells the two uploaded halves apart", () => {
  assert.equal(H.certFileKind(KEY), "key");
  assert.equal(H.certFileKind(LEAF), "cert");
  assert.equal(H.certFileKind("just some text"), null);
});

// --- the CORS fallback ---
const res = (body, ok = true, status = 200) =>
  ({ ok, status, text: async () => body, json: async () => JSON.parse(body) });

await (async () => {
  // direct fetch works: the proxy is never called
  let calls = [];
  let h = load(async (u) => { calls.push(u); return res(LEAF); });
  assert.equal(await h.fetchCertFile("ssl.combined"), LEAF);
  assert.deepEqual(calls, [H.CERT_SRC + "ssl.combined"]);
  console.log("ok - direct fetch is used when it succeeds"); groups++;

  // CORS refusal (TypeError) falls back to the proxy
  calls = [];
  h = load(async (u) => {
    calls.push(u);
    if (!u.startsWith("https://api.allorigins.win/")) throw new TypeError("Failed to fetch");
    return res(JSON.stringify({ contents: KEY }));
  });
  assert.equal(await h.fetchCertFile("ssl.key"), KEY);
  assert.equal(calls.length, 2);
  assert.ok(calls[1].includes(encodeURIComponent(H.CERT_SRC + "ssl.key")),
    "proxy must be given the url encoded");
  console.log("ok - a CORS refusal falls back to the proxy"); groups++;

  // a real HTTP answer is not proxied
  calls = [];
  h = load(async (u) => { calls.push(u); return res("nope", false, 404); });
  await rejects(h.fetchCertFile("ssl.key"), /ssl\.key 404/);
  assert.equal(calls.length, 1, "404 must not be retried through the proxy");
  console.log("ok - a 404 is reported, not proxied"); groups++;

  // a mock fetch that answers direct requests (CORS-refused) and each of the
  // three proxies independently, by URL shape
  const isDirect = (u) => u.startsWith(H.CERT_SRC);
  const isAllorigins = (u) => u.startsWith("https://api.allorigins.win/");
  const isCorsproxy = (u) => u.startsWith("https://corsproxy.io/");
  const isThingproxy = (u) => u.startsWith("https://thingproxy.freeboard.io/");
  const chained = (allorigins, corsproxy, thingproxy) => async (u) => {
    if (isDirect(u)) throw new TypeError("Failed to fetch");
    if (isAllorigins(u)) return allorigins(u);
    if (isCorsproxy(u)) return corsproxy(u);
    if (isThingproxy(u)) return thingproxy(u);
    throw new Error("unexpected url: " + u);
  };

  // the first proxy fails (a real error, not just CORS) but the second answers --
  // this is the whole point: one flaky proxy doesn't take the feature down
  calls = [];
  h = load((u) => { calls.push(u); return chained(
    () => res("", false, 502),
    () => res(KEY),
    () => { throw new Error("unreachable: thingproxy must not be tried"); },
  )(u); });
  assert.equal(await h.fetchCertFile("ssl.key"), KEY);
  assert.equal(calls.length, 3, "direct, then allorigins, then corsproxy.io");
  console.log("ok - a failed proxy is skipped in favour of the next one"); groups++;

  // every proxy fails: the error from the last one attempted is what surfaces
  h = load(chained(
    () => res("", false, 502),
    () => { throw new TypeError("Failed to fetch"); },
    () => res("", false, 504),
  ));
  await rejects(h.fetchCertFile("ssl.key"), /proxy 504/);
  console.log("ok - when every proxy fails, the last one's error is reported"); groups++;

  // an empty/invalid reply from a proxy is treated as a failure, same as an error status
  h = load(chained(
    () => res(JSON.stringify({ nope: 1 })),
    () => res("   "),
    () => res(KEY),
  ));
  assert.equal(await h.fetchCertFile("ssl.key"), KEY);
  console.log("ok - an empty or malformed proxy reply falls through to the next proxy"); groups++;

  // the whole point: a proxied HTML error page must never reach the hub
  h = load(async (u) => u.startsWith("https://api.allorigins.win/")
    ? res(JSON.stringify({ contents: "<html>Forbidden</html>" }))
    : (() => { throw new TypeError("Failed to fetch"); })());
  const bad = await h.fetchCertFile("ssl.combined");
  assert.throws(() => h.validateCertPair(bad, KEY), /found 0/);
  console.log("ok - a proxied error page fails validation before any push"); groups++;
})();

// --- the failure message itself: both files must be offered as links ---
{
  // certNote() lives outside the helper block because it touches the DOM; pull it
  // out by name and run it against a stub so the rendered nodes can be asserted.
  const i = html.indexOf("function certNote(");
  assert.ok(i > 0, "certNote not found");
  let depth = 0, end = html.indexOf("{", i);
  for (; end < html.length; end++) {
    if (html[end] === "{") depth++;
    else if (html[end] === "}" && --depth === 0) { end++; break; }
  }
  const el = {
    kids: [], textContent: "",
    append(x) { this.kids.push(x); },
    classList: { remove() {}, toggle() {} },
  };
  const document = { createElement: () => ({}) };
  const certNote = new Function("$", "document",
    `${html.slice(i, end)}\nreturn certNote;`)(() => el, document);

  certNote(["cert sync failed (x) - download ",
            { href: H.CERT_SRC + H.CERT_COMBINED, text: H.CERT_COMBINED }, " and ",
            { href: H.CERT_SRC + H.CERT_KEY, text: H.CERT_KEY },
            ", then use 'upload'. You can pick them one at a time."]);

  const links = el.kids.filter(k => typeof k === "object");
  assert.equal(links.length, 2, "both files must be offered");
  assert.deepEqual(links.map(a => a.href).sort(),
    [H.CERT_SRC + H.CERT_COMBINED, H.CERT_SRC + H.CERT_KEY]);
  assert.deepEqual(links.map(a => a.textContent).sort(), [H.CERT_COMBINED, H.CERT_KEY]);
  for (const a of links) { assert.equal(a.target, "_blank"); assert.equal(a.rel, "noopener"); }
  const said = el.kids.filter(k => typeof k === "string").join("");
  assert.match(said, /one at a time/, "must say the halves can be uploaded separately");
  groups++; console.log("ok - the failure message links both files and says one at a time");
}

console.log(`\n${groups} test groups passed`);
