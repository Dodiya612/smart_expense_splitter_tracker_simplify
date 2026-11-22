import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '../dist');

if (!fs.existsSync(distDir)) {
  console.error('Error: dist directory does not exist. Run expo export first.');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 1. Static HTTP Server serving mobile/dist
// ---------------------------------------------------------------------------
const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.css': 'text/css',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  let filePath = path.join(distDir, req.url === '/' ? 'index.html' : req.url.split('?')[0]);

  if (!fs.existsSync(filePath)) {
    filePath = path.join(distDir, 'index.html');
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(500);
      res.end('Server Error');
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
const baseUrl = 'http://127.0.0.1:8089';

console.log('--- Real Warm-Server Dashboard Performance Measurement ---');

try {
  // Warm-up run (ensures OS file cache and socket pools are warm)
  await fetch(`${baseUrl}/`);
  await fetch(`${baseUrl}/home.html`);

  const iterations = 5;
  const measurements = [];

  for (let i = 1; i <= iterations; i++) {
    const t0 = performance.now();

    // 1. Request root HTML document
    const tHtmlStart = performance.now();
    const docRes = await fetch(`${baseUrl}/home.html`);
    const docHtml = await docRes.text();
    const tHtmlEnd = performance.now();
    const htmlDuration = tHtmlEnd - tHtmlStart;

    // 2. Extract script URLs (the initial shell)
    const scriptRegex = /<script\s+src="([^"]+)"/g;
    const scripts = [];
    let match;
    while ((match = scriptRegex.exec(docHtml)) !== null) {
      scripts.push(match[1]);
    }

    // 3. Download shell scripts in parallel (as a real browser does)
    const tShellStart = performance.now();
    const shellPromises = scripts.map((src) => fetch(`${baseUrl}${src}`).then((r) => r.text()));
    await Promise.all(shellPromises);
    const tShellEnd = performance.now();
    const shellDuration = tShellEnd - tShellStart;

    // 4. Download dynamically loaded HomeScreen route chunk
    const jsDir = path.join(distDir, '_expo/static/js/web');
    const files = fs.readdirSync(jsDir);
    const homeChunkFile = files.find((f) => f.startsWith('HomeScreen-') && f.endsWith('.js'));

    const tChunkStart = performance.now();
    const chunkRes = await fetch(`${baseUrl}/_expo/static/js/web/${homeChunkFile}`);
    await chunkRes.text();
    const tChunkEnd = performance.now();
    const chunkDuration = tChunkEnd - tChunkStart;

    const totalDuration = performance.now() - t0;
    measurements.push({
      iteration: i,
      htmlDuration,
      shellDuration,
      chunkDuration,
      totalDuration,
    });
  }

  console.log('\nMeasured Iterations (Warm Server):');
  for (const m of measurements) {
    console.log(
      `Iteration #${m.iteration}: HTML = ${m.htmlDuration.toFixed(2)}ms | Shell = ${m.shellDuration.toFixed(2)}ms | HomeScreen Chunk = ${m.chunkDuration.toFixed(2)}ms | Total E2E = ${m.totalDuration.toFixed(2)}ms`
    );
  }

  const avgTotal = measurements.reduce((sum, m) => sum + m.totalDuration, 0) / iterations;
  const avgHtml = measurements.reduce((sum, m) => sum + m.htmlDuration, 0) / iterations;
  const avgShell = measurements.reduce((sum, m) => sum + m.shellDuration, 0) / iterations;
  const avgChunk = measurements.reduce((sum, m) => sum + m.chunkDuration, 0) / iterations;

  console.log('\nSummary Performance Metrics:');
  console.log(`Average Document TTFB:     ${avgHtml.toFixed(2)} ms`);
  console.log(`Average Shell Bundles:     ${avgShell.toFixed(2)} ms`);
  console.log(`Average Dynamic Chunk:     ${avgChunk.toFixed(2)} ms`);
  console.log(`Average Total E2E Load:    ${avgTotal.toFixed(2)} ms`);
  console.log(`Target:                    < 3,000.00 ms (< 3.0 seconds)`);
  console.log(
    `Verdict:                   ${avgTotal < 3000 ? 'PASS (Under 3 seconds)' : 'FAIL (Exceeds 3 seconds)'}`
  );
} finally {
  server.close();
}
