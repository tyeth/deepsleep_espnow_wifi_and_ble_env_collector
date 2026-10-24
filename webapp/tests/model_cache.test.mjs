import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {webcrypto} from "node:crypto";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {test} from "node:test";
const require = createRequire(import.meta.url);
const {createModelCache} = require("../prompt_backend.js");
const url = "https://huggingface.co/org/model/resolve/revision/onnx/model_quantized.onnx";

function storage() {
  const files = new Map(), small = new Map(), writes = [];
  const state = {files, small, writes, failWrite: false, failClose: false, smallWrites: 0};
  const directory = {
    async getFileHandle(name, {create = false} = {}) {
      if (!files.has(name)) {
        if (!create) throw new DOMException("missing", "NotFoundError");
        files.set(name, new Blob([]));
      }
      return {
        async getFile() { return files.get(name); },
        async createWritable() {
          const pending = [];
          return {
            async write(chunk) {
              writes.push(chunk.byteLength);
              if (state.failWrite) throw new DOMException("full", "QuotaExceededError");
              pending.push(chunk.slice());
            },
            async close() {
              if (state.failClose) throw Error("commit failed");
              files.set(name, new Blob(pending));
            },
            async abort() { pending.length = 0; },
          };
        },
      };
    },
  };
  state.host = {
    crypto: webcrypto,
    location: {href: "https://portal.example/"},
    navigator: {storage: {async getDirectory() { return {async getDirectoryHandle() { return directory; }}; }}},
    console: {warn() {}},
    caches: {async open() { return {
      async match(key) { return small.get(key)?.clone(); },
      async put(key, response) { state.smallWrites++; small.set(key, response.clone()); },
    }; }},
  };
  return state;
}

test("weights survive a new cache instance and each write is bounded", async () => {
  const state = storage(), bytes = new Uint8Array(9 * 1024 * 1024 + 17).fill(93);
  await (await createModelCache(state.host)).put(url, new Response(bytes, {headers: {"Content-Length": String(bytes.length)}}));
  const loaded = await (await createModelCache(state.host)).match(url);
  assert.equal(loaded.headers.get("Content-Length"), String(bytes.length));
  assert.deepEqual(new Uint8Array(await loaded.arrayBuffer()), bytes);
  assert.ok(state.writes.length > 1);
  assert.ok(state.writes.every(size => size <= 4 * 1024 * 1024));
  assert.equal(state.smallWrites, 0);
});

test("truncated first downloads are misses and failed replacements preserve the old model", async () => {
  const state = storage(), cache = await createModelCache(state.host);
  const truncated = () => new Response("short", {headers: {"Content-Length": "20"}});
  await assert.rejects(cache.put(url, truncated()), /Incomplete/);
  assert.equal(await cache.match(url), undefined);
  await cache.put(url, new Response("complete"));
  await assert.rejects(cache.put(url, truncated()), /Incomplete/);
  assert.equal(await (await cache.match(url)).text(), "complete");
  state.failWrite = true;
  await assert.rejects(cache.put(url, new Response("replacement")), /full/);
  assert.equal(await (await cache.match(url)).text(), "complete");
  state.failWrite = false; state.failClose = true;
  await assert.rejects(cache.put(url, new Response("replacement")), /commit failed/);
  assert.equal(await (await cache.match(url)).text(), "complete");
});

test("partial and empty model responses are never committed", async () => {
  const state = storage(), cache = await createModelCache(state.host);
  await assert.rejects(cache.put(url, new Response("range", {status: 206})), /partial/);
  await assert.rejects(cache.put(url, new Response("")), /Incomplete/);
  assert.equal(await cache.match(url), undefined);
});

test("small files and previously cached weights remain usable", async () => {
  const state = storage(), cache = await createModelCache(state.host);
  const config = "https://huggingface.co/org/model/resolve/revision/config.json";
  await cache.put(config, new Response('{"ready":true}'));
  assert.deepEqual(await (await cache.match(config)).json(), {ready: true});
  state.small.set(url, new Response("old browser cache"));
  assert.equal(await (await cache.match(url)).text(), "old browser cache");
  assert.equal(state.files.size, 0);
});

test("revision and dtype use distinct files; unavailable OPFS leaves the default loader intact", async () => {
  const state = storage(), cache = await createModelCache(state.host);
  const other = url.replace("revision", "next");
  await cache.put(url, new Response("first"));
  await cache.put(other, new Response("second"));
  assert.equal(await (await cache.match(url)).text(), "first");
  assert.equal(await (await cache.match(other)).text(), "second");
  assert.equal(await createModelCache({}), null);
  state.host.navigator.storage.getDirectory = async () => {throw Error("denied");};
  assert.equal(await createModelCache(state.host), null);
});

test("service-worker activation removes only older app-shell versions", async () => {
  const handlers = {}, deleted = [];
  vm.runInNewContext(await readFile(new URL("../sw.js", import.meta.url), "utf8"), {
    self: {addEventListener(name, handler) {handlers[name] = handler;}, skipWaiting() {}, clients: {claim() {}}},
    caches: {
      async keys() {return ["envhub-v1", "envhub-v19", "envhub-v20", "envhub-v21", "transformers-cache", "another-app", "envhub-models-v1"];},
      async delete(key) {deleted.push(key);},
    },
  });
  let finished;
  handlers.activate({waitUntil(promise) {finished = promise;}});
  await finished;
  assert.deepEqual(deleted.sort(), ["envhub-v1", "envhub-v19", "envhub-v20"]);
});
