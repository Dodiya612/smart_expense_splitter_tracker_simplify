import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '../dist');

if (!fs.existsSync(distDir)) {
  console.error('Error: dist directory does not exist.');
  process.exit(1);
}

// 1. Static HTTP Server
const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.css': 'text/css',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  let filePath = path.join(distDir, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
  if (!fs.existsSync(filePath)) filePath = path.join(distDir, 'index.html');
  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(500);
      res.end('Error');
      return;
    }
    res.writeHead(200, {
      'Content-Type': contentType,
      'Cache-Control': 'public, max-age=3600',
    });
    res.end(data);
  });
});

await new Promise((resolve) => server.listen(8089, '127.0.0.1', resolve));

// 2. Launch Chrome Headless
const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-bench-'));
const chromeProcess = spawn(
  chromePath,
  [
    '--headless=new',
    '--remote-debugging-port=9222',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    `--user-data-dir=${userDataDir}`,
  ],
  { stdio: 'ignore' }
);

// Wait for Chrome remote debugging port
let wsUrl = null;
for (let i = 0; i < 30; i++) {
  await new Promise((r) => setTimeout(r, 200));
  try {
    const res = await fetch('http://127.0.0.1:9222/json/version');
    const data = await res.json();
    wsUrl = data.webSocketDebuggerUrl;
    if (wsUrl) break;
  } catch {}
}

if (!wsUrl) {
  console.error('Could not connect to Chrome CDP.');
  chromeProcess.kill();
  server.close();
  process.exit(1);
}

// Simple CDP client over global WebSocket
const ws = new WebSocket(wsUrl);
await new Promise((resolve) => {
  ws.onopen = resolve;
});

let msgId = 1;
const pending = new Map();
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(msg.error);
    else resolve(msg.result);
  }
};

function send(method, params = {}) {
  const id = msgId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

// Create new target/tab
const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });

function sendSession(method, params = {}) {
  const id = msgId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}

await sendSession('Page.enable');
await sendSession('Runtime.enable');

console.log('--- Real Browser (Google Chrome) Warm-Server Dashboard Benchmark ---');

try {
  // Warm-up run
  await sendSession('Page.navigate', { url: 'http://127.0.0.1:8089/' });
  await new Promise((r) => setTimeout(r, 1000));

  const measurements = [];
  const iterations = 5;

  for (let i = 1; i <= iterations; i++) {
    const navStart = performance.now();
    await sendSession('Page.navigate', { url: 'http://127.0.0.1:8089/' });

    // Poll until dashboard rendered and usable in real browser DOM
    let isRendered = false;
    let timing = null;

    for (let poll = 0; poll < 60; poll++) {
      await new Promise((r) => setTimeout(r, 50));
      const evalRes = await sendSession('Runtime.evaluate', {
        expression: `(() => {
          const nav = performance.getEntriesByType('navigation')[0];
          const paints = performance.getEntriesByType('paint');
          const fcp = paints.find(p => p.name === 'first-contentful-paint');
          const hasContent = document.body && (
            document.body.innerText.includes('Spent this month') ||
            document.body.innerText.includes('Recent Expenses') ||
            document.body.innerText.includes('Total') ||
            document.body.innerText.length > 100
          );
          if (!nav || !hasContent) return null;
          return {
            ttfb: Math.round(nav.responseStart - nav.startTime),
            domInteractive: Math.round(nav.domInteractive - nav.startTime),
            domComplete: Math.round(nav.domComplete - nav.startTime),
            loadEventEnd: Math.round(nav.loadEventEnd - nav.startTime),
            fcp: fcp ? Math.round(fcp.startTime) : null,
          };
        })()`,
        returnByValue: true,
      });

      if (evalRes.result && evalRes.result.value) {
        timing = evalRes.result.value;
        isRendered = true;
        break;
      }
    }

    const totalBrowserRenderMs = performance.now() - navStart;
    measurements.push({
      iteration: i,
      totalBrowserRenderMs: Math.round(totalBrowserRenderMs),
      ...timing,
    });
  }

  console.log('\nMeasured Real Chrome Executions:');
  for (const m of measurements) {
    console.log(
      `Run #${m.iteration}: TTFB = ${m.ttfb}ms | FCP = ${m.fcp ?? 'N/A'}ms | DOM Interactive = ${m.domInteractive}ms | DOM Complete = ${m.domComplete}ms | Total Visible & Usable = ${m.totalBrowserRenderMs}ms`
    );
  }

  const avgTotal =
    measurements.reduce((sum, m) => sum + m.totalBrowserRenderMs, 0) / iterations;
  const avgFcp =
    measurements.reduce((sum, m) => sum + (m.fcp || m.domInteractive), 0) / iterations;
  const avgInteractive =
    measurements.reduce((sum, m) => sum + m.domInteractive, 0) / iterations;

  console.log('\nAggregate Browser Metrics (5 Warm Runs):');
  console.log(`Average First Contentful Paint:   ${avgFcp.toFixed(1)} ms`);
  console.log(`Average DOM Interactive:          ${avgInteractive.toFixed(1)} ms`);
  console.log(`Average Fully Rendered & Usable:  ${avgTotal.toFixed(1)} ms`);
  console.log(`Performance Target:               < 3,000.0 ms (< 3.0 seconds)`);
  console.log(
    `Acceptance Status:                ${avgTotal < 3000 ? 'PASS (Under 3 seconds)' : 'FAIL'}`
  );
} finally {
  ws.close();
  chromeProcess.kill();
  server.close();
  try {
    fs.rmSync(userDataDir, { recursive: true, force: true });
  } catch {}
}
