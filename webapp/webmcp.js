/* Env Hub's read-only browser tools. No model or network dependency. */
(function (root) {
  "use strict";
  async function register({context, secure, metadata, schema, query}) {
    if (!secure || typeof context?.registerTool !== "function") return null;
    const lifetime = new AbortController();
    const safe = fn => async (args, options = {}) => {
      try {
        options.signal?.throwIfAborted();
        const result = await fn(args, options.signal);
        options.signal?.throwIfAborted();
        return result;
      } catch (error) {
        return {error: String(error.message || error)};
      }
    };
    const annotations = {readOnlyHint: true, untrustedContentHint: true};
    try {
      await context.registerTool({
        name: "envhub_dataset",
        description: "Describe the environmental readings loaded in this page: zones, UTC date range, row count and SQL schema. Load or sync data in the page first.",
        inputSchema: {type: "object", properties: {}, additionalProperties: false},
        annotations,
        execute: safe(() => ({...metadata(), schema: schema()})),
      }, {signal: lifetime.signal});
      await context.registerTool({
        name: "envhub_query",
        description: "Query loaded environmental readings with one read-only SQLite SELECT. Prefer aggregates. Results are limited to 50 rows. Does not contact, configure or calibrate hardware.",
        inputSchema: {type: "object", properties: {sql: {type: "string"}}, required: ["sql"], additionalProperties: false},
        annotations,
        execute: safe(async (args, signal) => {
          if (typeof args?.sql !== "string" || !args.sql.trim()) throw new Error("sql must be a nonempty string");
          if (!metadata().rows) throw new Error("No data loaded. Use Load & merge in the page first.");
          return query(args.sql, signal);
        }),
      }, {signal: lifetime.signal});
    } catch (error) {
      lifetime.abort(); // Do not leave half a tool set registered.
      throw error;
    }
    return () => lifetime.abort();
  }
  const api = {register};
  if (typeof module !== "undefined") module.exports = api;
  else root.EnvWebMCP = api;
})(globalThis);
