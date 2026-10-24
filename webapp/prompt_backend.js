/* Native Prompt API first; explicitly enabled local polyfill for phones. */
(function (root) {
  "use strict";
  const POLYFILL_URL = "https://cdn.jsdelivr.net/npm/prompt-api-polyfill@1.22.2/dist/prompt-api-polyfill.js";
  // Android Cache.put failed for the 512 MB weight response. Keep small
  // runtime/config files in Cache Storage, and stream weights into OPFS.
  // createWritable publishes the replacement only when close succeeds.
  async function createModelCache(host = root) {
    if (!host.navigator?.storage?.getDirectory || !host.caches || !host.crypto?.subtle) return null;
    let directory, small;
    try {
      directory = await (await host.navigator.storage.getDirectory())
        .getDirectoryHandle("envhub-models-v1", {create: true});
      small = await host.caches.open("transformers-cache");
    } catch (error) {
      host.console?.warn("Local model file storage is unavailable; using browser cache.", error);
      return null;
    }
    async function filename(request) {
      const value = typeof request === "string" ? request : request.url || String(request);
      let url;
      try { url = new URL(value, host.location?.href); } catch (_) { return null; }
      if (!/^https?:$/.test(url.protocol) || !/\.onnx(?:_data)?$/.test(url.pathname)) return null;
      const digest = await host.crypto.subtle.digest("SHA-256", new TextEncoder().encode(url.href));
      return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("") + ".onnx";
    }
    return {
      async match(request) {
        const name = await filename(request);
        if (name) {
          try {
            const file = await (await directory.getFileHandle(name)).getFile();
            // A first write that was interrupted can leave an empty handle.
            if (file.size) return new Response(file, {headers: {
              "Content-Type": "application/octet-stream", "Content-Length": String(file.size),
            }});
          } catch (error) {
            if (error.name !== "NotFoundError") host.console?.warn("Cannot read saved model.", error);
          }
        }
        // Reuse weights retained by older versions or other supported browsers.
        return small.match(request);
      },
      async put(request, response) {
        const name = await filename(request);
        if (!name) return small.put(request, response);
        if (response.status !== 200 || !response.body) throw new Error("Cannot save a partial model response.");
        const expected = response.headers.get("Content-Length");
        const writer = await (await directory.getFileHandle(name, {create: true})).createWritable();
        const reader = response.body.getReader();
        let size = 0;
        try {
          for (;;) {
            const {done, value} = await reader.read();
            if (done) break;
            // Transformers can hand us the entire ArrayBuffer as one chunk.
            // Bound each browser storage write, without copying the whole model.
            for (let offset = 0; offset < value.byteLength; offset += 4 * 1024 * 1024) {
              const chunk = value.subarray(offset, offset + 4 * 1024 * 1024);
              await writer.write(chunk);
              size += chunk.byteLength;
            }
          }
          if (!size || (expected !== null && size !== Number(expected))) throw new Error("Incomplete model download; not saved.");
          await writer.close();
        } catch (error) {
          await writer.abort().catch(() => {});
          await reader.cancel().catch(() => {});
          throw error;
        } finally {
          reader.releaseLock();
        }
      },
    };
  }
  function createResolver(host = root, load = url => import(url)) {
    let pending = null;
    let local = false;
    const native = host.LanguageModel;
    return {
      get local() { return local; },
      async resolve({allowLocal = false, nativeUnavailable = false, signal} = {}) {
        signal?.throwIfAborted();
        if (!nativeUnavailable && typeof native?.create === "function") { local = false; return native; }
        if (!allowLocal) { local = false; return null; }
        if (!host.isSecureContext) throw new Error("Local AI needs HTTPS or localhost.");
        // Configure only a local backend; never send readings to a cloud provider.
        if (["FIREBASE_CONFIG", "GEMINI_CONFIG", "OPENAI_CONFIG", "WEBLLM_CONFIG"].some(k => host[k])) {
          throw new Error("Another AI backend is configured. Reload the page before enabling local AI.");
        }
        if (!pending) {
          pending = (async () => {
            // Prefer acceleration where the browser supplies an adapter.
            // WASM in a worker remains available on phones without WebGPU.
            // q4f16 produced incorrect inference on the tested AMD GPU despite
            // shader-f16 support. Keep full-precision arithmetic with q4 weights.
            let device = "wasm", dtype = "q4";
            try {
              const adapter = await host.navigator?.gpu?.requestAdapter();
              if (adapter) device = "webgpu";
            } catch (_) {}
            // The fully quantized q8 file is smaller than this model's q4
            // file. Keep the separately validated q4 setting on WebGPU.
            if (device === "wasm") dtype = "q8";
            const cache = await createModelCache(host);
            host.TRANSFORMERS_CONFIG = {
              apiKey: "dummy",
              modelName: "onnx-community/Qwen2.5-0.5B-Instruct",
              device,
              dtype,
              // Keep WASM inference off the UI thread so Stop remains usable.
              env: {
                ...(cache ? {useCustomCache: true, customCache: cache} : {}),
                backends: {onnx: {wasm: {proxy: device === "wasm", numThreads: 1}}},
              },
            };
            const module = await load(POLYFILL_URL);
            const model = module?.LanguageModel || host.LanguageModel;
            if (typeof model?.create !== "function" || model === native) throw new Error("Prompt API polyfill did not load.");
            return model;
          })().catch(error => { pending = null; throw error; });
        }
        const model = await pending;
        signal?.throwIfAborted();
        local = true;
        return model;
      },
    };
  }
  function progress(event) {
    const loaded = Number(event.loaded);
    if (!Number.isFinite(loaded)) return null;
    const total = Number(event.total);
    return Math.max(0, Math.min(1, total > 0 ? loaded / total : loaded));
  }
  function systemPrompt(schema) {
    const context = String(schema).split("\n").filter(line => /^(zones present:|data range:)/.test(line)).join("\n");
    return `Translate the question into a SQLite SELECT. Output only SQL.
Table readings(src TEXT, ts INTEGER, co2 REAL, tc REAL, rh REAL, pm1 REAL, pm25 REAL, pm4 REAL, pm10 REAL, voc REAL, nox REAL, vb REAL).
src means zone. ts is Unix time in seconds. co2 means CO2 ppm. tc means Celsius temperature. rh means humidity percent. pm columns are particulates in ug/m3. voc and nox are indices. vb is battery volts.
Each zone means GROUP BY src. Highest means MAX. Lowest means MIN. Average means AVG.
Use readings only. Do not invent another question or include explanations.
${context}`;
  }
  function queryPrompts(question) {
    return [
      {role: "user", content: "Highest humidity in each zone?"},
      {role: "assistant", content: "SELECT src, MAX(rh) AS peak_humidity FROM readings GROUP BY src"},
      {role: "user", content: "Lowest temperature in each zone?"},
      {role: "assistant", content: "SELECT src, MIN(tc) AS low_temperature FROM readings GROUP BY src"},
      {role: "user", content: question},
    ];
  }
  function queryText(reply) {
    const text = String(reply).trim();
    // A small model can continue with another example after its answer. Take
    // only the first explicitly fenced SQL block, even after a preface;
    // validate that whole block, including any additional statements.
    const fenced = /(?:^|\n)```(?:sql)?[ \t]*\r?\n([\s\S]*?)\r?\n```/i.exec(text);
    return (fenced ? fenced[1] : text).trim();
  }
  const api = {createModelCache, createResolver, progress, systemPrompt, queryPrompts, queryText, POLYFILL_URL};
  if (typeof module !== "undefined") module.exports = api;
  else root.EnvPromptBackend = api;
})(globalThis);
