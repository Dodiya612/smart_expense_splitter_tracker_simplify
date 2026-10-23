/**
 * Verification script demonstrating that client can call the health endpoint
 * through the generated TypeScript client and handles consistent error envelopes.
 */
import { CoinsciousClient } from "./src/client.js";

async function verifyClient() {
  const baseUrl = process.env.API_BASE_URL || "http://127.0.0.1:8000";
  console.log(`[CLIENT-VERIFY] Connecting to Coinscious Backend at: ${baseUrl}`);

  const client = new CoinsciousClient({ baseUrl });

  try {
    // 1. Call GET /api/v1/health through client.health.check()
    console.log("[CLIENT-VERIFY] 1. Executing client.health.check()...");
    const health = await client.health.check({
      "X-Request-ID": "req_client_verify_test",
    });

    console.log("[CLIENT-VERIFY] Received typed HealthResponse:");
    console.log(JSON.stringify(health, null, 2));

    // Assertions matching contract
    if (health.status !== "ok") {
      throw new Error(`Expected status 'ok', got '${health.status}'`);
    }
    if (!health.environment) {
      throw new Error("Missing environment field in health response");
    }
    if (!health.version) {
      throw new Error("Missing version field in health response");
    }
    if (!health.timestamp || isNaN(Date.parse(health.timestamp))) {
      throw new Error(`Invalid ISO timestamp: ${health.timestamp}`);
    }
    console.log(" -> [PASS] Health check returned expected payload.");

    // 2. Call non-existent endpoint to verify standard 404 ErrorResponse envelope
    console.log("[CLIENT-VERIFY] 2. Verifying 404 ErrorResponse envelope...");
    try {
      await client.request("/api/v1/non-existent-endpoint");
      throw new Error("Expected 404 ErrorResponse, but request succeeded unexpectedly.");
    } catch (err) {
      if (!err.error || !err.meta) {
        throw new Error(`Invalid error envelope received: ${JSON.stringify(err)}`);
      }
      if (err.error.code !== "NOT_FOUND") {
        throw new Error(`Expected error code 'NOT_FOUND', got '${err.error.code}'`);
      }
      if (!err.meta.request_id || !err.meta.request_id.startsWith("req_")) {
        throw new Error(`Expected request_id starting with 'req_', got '${err.meta.request_id}'`);
      }
      console.log(` -> [PASS] 404 returned standard ErrorResponse [code=${err.error.code}, req_id=${err.meta.request_id}].`);
    }

    // 3. Call invalid HTTP method (POST on GET-only /api/v1/health) to verify 405 envelope
    console.log("[CLIENT-VERIFY] 3. Verifying 405 METHOD_NOT_ALLOWED envelope...");
    try {
      await client.request("/api/v1/health", {
        method: "POST",
        body: { test: "invalid" },
      });
      throw new Error("Expected 405 error, but request succeeded unexpectedly.");
    } catch (err) {
      if (!err.error || !err.meta) {
        throw new Error(`Invalid error envelope received: ${JSON.stringify(err)}`);
      }
      if (err.error.code !== "METHOD_NOT_ALLOWED") {
        throw new Error(`Expected METHOD_NOT_ALLOWED, got: ${JSON.stringify(err)}`);
      }
      if (!err.meta.request_id || !err.meta.request_id.startsWith("req_")) {
        throw new Error(`Expected request_id starting with 'req_', got '${err.meta.request_id}'`);
      }
      console.log(` -> [PASS] 405 returned METHOD_NOT_ALLOWED envelope [code=${err.error.code}, req_id=${err.meta.request_id}].`);
    }

    console.log("\n==========================================================================");
    console.log("[CLIENT-VERIFY] ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!");
    console.log("==========================================================================");
    process.exit(0);
  } catch (error) {
    console.error("\n[CLIENT-VERIFY] FAILED: Verification check failed:", error);
    process.exit(1);
  }
}

verifyClient();
