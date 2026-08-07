/**
 * pdf2word - Node.js gateway in front of the Flask backend.
 *
 * Responsibilities:
 *   - boot and supervise the Flask process (restarting it if it dies)
 *   - serve /static/* straight from disk (no Python round-trip)
 *   - stream everything else to Flask, including 100MB uploads and
 *     long-lived download responses
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = Number(process.env.PORT) || 3000;
const FLASK_PORT = Number(process.env.FLASK_PORT) || 5001;
const FLASK_HOST = '127.0.0.1';

const MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
};

const STATIC_ROOT = path.join(__dirname, 'static');

// ---------------------------------------------------------------------------
// Flask supervisor
// ---------------------------------------------------------------------------
let flaskProcess = null;
let shuttingDown = false;

function startFlask() {
    flaskProcess = spawn('python3', ['-u', 'app.py'], {
        cwd: __dirname,
        env: { ...process.env, PORT: String(FLASK_PORT), PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'inherit', 'inherit'],
    });

    flaskProcess.on('exit', (code, signal) => {
        if (shuttingDown) return;
        console.error(`[gateway] Flask exited (code=${code}, signal=${signal}); restarting in 1s`);
        setTimeout(startFlask, 1000);
    });
}

startFlask();

function stopFlask() {
    shuttingDown = true;
    if (flaskProcess && !flaskProcess.killed) {
        flaskProcess.kill('SIGTERM');
    }
}

process.on('exit', stopFlask);
process.on('SIGINT', () => { stopFlask(); process.exit(0); });
process.on('SIGTERM', () => { stopFlask(); process.exit(0); });

// ---------------------------------------------------------------------------
// Readiness probe: poll Flask /health until it answers
// ---------------------------------------------------------------------------
let flaskReady = false;
const readyWaiters = [];

function pingFlask() {
    const req = http.request(
        { host: FLASK_HOST, port: FLASK_PORT, path: '/health', method: 'GET', timeout: 2000 },
        (res) => {
            res.resume();
            if (res.statusCode === 200) {
                if (!flaskReady) console.log('[gateway] Flask backend is ready');
                flaskReady = true;
                while (readyWaiters.length) readyWaiters.shift()();
            } else {
                setTimeout(pingFlask, 300);
            }
        }
    );
    req.on('error', () => setTimeout(pingFlask, 300));
    req.on('timeout', () => { req.destroy(); });
    req.end();
}

pingFlask();

function whenReady() {
    if (flaskReady) return Promise.resolve();
    return new Promise((resolve) => {
        readyWaiters.push(resolve);
        setTimeout(resolve, 30000); // never hang a request forever
    });
}

// ---------------------------------------------------------------------------
// Proxy
// ---------------------------------------------------------------------------
function proxyToFlask(req, res) {
    const headers = { ...req.headers, host: `${FLASK_HOST}:${FLASK_PORT}` };
    delete headers['accept-encoding']; // keep the byte stream verbatim

    const proxyReq = http.request(
        {
            hostname: FLASK_HOST,
            port: FLASK_PORT,
            path: req.url,
            method: req.method,
            headers,
        },
        (proxyRes) => {
            res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
            proxyRes.pipe(res);
        }
    );

    // Conversions can take minutes; never cut the socket from this side.
    proxyReq.setTimeout(0);

    proxyReq.on('error', (err) => {
        console.error('[gateway] proxy error:', err.message);
        if (!res.headersSent) {
            res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
        }
        res.end(JSON.stringify({ error: 'Conversion backend unavailable. Please retry.' }));
    });

    req.on('aborted', () => proxyReq.destroy());
    req.pipe(proxyReq);
}

function serveStatic(pathname, res) {
    const resolved = path.join(STATIC_ROOT, pathname.replace(/^\/static\/?/, ''));

    // Block path traversal outside static/
    if (!resolved.startsWith(STATIC_ROOT)) {
        res.writeHead(403, { 'Content-Type': 'text/plain' });
        res.end('Forbidden');
        return true;
    }

    let stats;
    try {
        stats = fs.statSync(resolved);
    } catch (err) {
        return false;
    }
    if (!stats.isFile()) return false;

    res.writeHead(200, {
        'Content-Type': MIME_TYPES[path.extname(resolved)] || 'application/octet-stream',
        'Content-Length': stats.size,
        'Cache-Control': 'public, max-age=3600',
    });
    fs.createReadStream(resolved).pipe(res);
    return true;
}

const server = http.createServer(async (req, res) => {
    let pathname;
    try {
        pathname = new URL(req.url, `http://${req.headers.host || 'localhost'}`).pathname;
    } catch (err) {
        pathname = req.url.split('?')[0];
    }

    if (pathname.startsWith('/static/') && serveStatic(pathname, res)) {
        return;
    }

    await whenReady();
    proxyToFlask(req, res);
});

// 100MB uploads must not trip Node's default request timeout.
server.requestTimeout = 0;
server.headersTimeout = 120000;
server.keepAliveTimeout = 75000;
server.timeout = 0;

server.listen(PORT, '0.0.0.0', () => {
    console.log(`[gateway] pdf2word listening on http://0.0.0.0:${PORT}`);
    console.log(`[gateway] Flask backend on port ${FLASK_PORT}`);
});

server.on('error', (err) => {
    console.error('[gateway] server error:', err);
    process.exit(1);
});
