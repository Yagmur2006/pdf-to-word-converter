# DocuSwift — PDF to Word Converter

A premium, minimal SaaS-style PDF → DOCX converter built for students,
teachers, researchers and office staff. Zero learning curve: drag a
PDF in, get a Word document out.

## Tech stack

| Layer        | Technology                                    |
|--------------|------------------------------------------------|
| Frontend     | HTML5, CSS3 (custom design system), Vanilla JS (ES6 modules, `fetch`) |
| Backend      | PHP 8.2+ (no framework, modular classes)       |
| Conversion   | Python 3 + [`pdf2docx`](https://pypi.org/project/pdf2docx/), invoked via `proc_open` |
| Server       | Apache or Nginx (config examples in `/deploy`) |

No jQuery, no build step, no bundler required — everything runs as static
assets + plain PHP scripts.

## Project structure

```
pdf2word/
├── index.html              # Single-page app (Home)
├── assets/
│   ├── css/styles.css      # Design tokens + components
│   ├── js/
│   │   ├── api.js          # fetch() wrappers for every endpoint
│   │   ├── ui.js            # DOM helpers (state switching, formatting)
│   │   └── main.js          # App orchestration / event wiring
│   └── images/              # favicon, OG image (SVG, no build needed)
├── api/
│   ├── csrf.php             # Issues CSRF token for the session
│   ├── upload.php           # Validates + stores upload, starts job
│   ├── status.php           # Polled for job progress
│   └── download.php         # Streams DOCX, then purges the job
├── includes/
│   ├── bootstrap.php        # Shared init: sessions, error handling, autoload
│   ├── Config.php           # Single source of truth for paths/limits
│   ├── Logger.php           # JSON line file logger
│   ├── Security.php         # CSRF tokens, random IDs, sanitizing
│   ├── RateLimiter.php      # File-based fixed-window rate limiting
│   ├── FileValidator.php    # Extension + real MIME + magic-byte checks
│   ├── JobManager.php       # Job lifecycle: create, launch, status, purge
│   └── Response.php         # Standard JSON response envelope
├── scripts/
│   ├── convert.py           # Python worker: PDF -> DOCX + progress JSON
│   └── cleanup.php          # Cron-friendly expired-file sweeper
├── uploads/                 # Temp PDFs (random names, .htaccess denies access)
├── converted/               # Temp DOCX output (same protection)
├── logs/                    # App logs + rate-limit state
├── deploy/                  # Example Apache/Nginx configs
└── requirements.txt         # Python dependency (pdf2docx)
```

## How a conversion works

1. **Upload** — Browser posts the PDF with a CSRF token to `api/upload.php`.
   The file is validated (extension, real MIME via `fileinfo`, magic bytes,
   size ≤ 100MB), stored under a random 32-hex-char name, and the endpoint
   returns a `jobId` immediately (HTTP 202) — it does **not** wait for
   conversion to finish.
2. **Background conversion** — `JobManager::launchWorker()` starts
   `scripts/convert.py` via `proc_open()` with `bypass_shell => true`
   (arguments passed directly to `execve`, no shell interpolation, so
   there is no command-injection surface). stdout/stderr are redirected to
   a log file rather than a PHP-side pipe, and `proc_close()` is
   deliberately **not** called — that's what keeps the HTTP request from
   blocking while the conversion runs.
3. **Progress polling** — The Python worker writes small JSON status
   updates (`queued → processing → done/error`, plus a message like
   "Extracting text and layout...") to a status file. The frontend polls
   `api/status.php` every ~1.2s and animates the progress bar accordingly.
4. **Download** — Once `state: done`, the UI reveals the download button
   pointing at `api/download.php?jobId=...`. That endpoint streams the
   file with a sanitized, original-derived filename and **immediately
   deletes all job artifacts** after the transfer — files are single-use.
5. **Retention & cleanup** — Even if a user never downloads their file,
   `Config::retentionMinutes()` (default 30) bounds how long anything sits
   on disk. Cleanup runs opportunistically (5% of API requests) and can
   also be scheduled via `scripts/cleanup.php` on cron for guaranteed
   sweeping under low traffic.

## Security checklist

- ✅ Extension **and** real-content MIME/magic-byte validation (never trusts
  the client's `Content-Type` header or filename).
- ✅ CSRF token required for uploads, tied to a `HttpOnly`, `SameSite=Strict`
  session cookie.
- ✅ Per-IP fixed-window rate limiting (20 requests / 10 minutes by default).
- ✅ Random, non-guessable filenames — the user's original name is only
  ever used for display/download, never for path construction.
- ✅ `proc_open` with `bypass_shell` — arguments never pass through `/bin/sh`.
- ✅ Storage folders (`uploads/`, `converted/`, `logs/`, `includes/`,
  `scripts/`) are denied via `.htaccess` (Apache) / `location` blocks
  (Nginx) — see `/deploy`.
- ✅ Files auto-expire after 30 minutes and are deleted immediately after
  a successful download.
- ✅ All error output is logged, never echoed to the client (no stack
  traces or paths leak in responses).

## Local development

```bash
# 1. Install the Python conversion dependency
pip3 install -r requirements.txt

# 2. (Optional) point PHP at a specific python binary
export PDF2WORD_PYTHON_BIN=python3

# 3. Serve with PHP's built-in server
php -S 127.0.0.1:8000

# 4. Open http://127.0.0.1:8000/index.html
```

For production, use the Apache or Nginx example configs in `/deploy`, and
make sure `upload_max_filesize` / `post_max_size` in `php.ini` are at
least 100MB to match `Config::maxUploadBytes()`. Also schedule
`scripts/cleanup.php` via cron for guaranteed retention enforcement:

```
*/5 * * * * php /var/www/pdf2word/scripts/cleanup.php >> /var/log/pdf2word-cleanup.log 2>&1
```

## Extending the app

The architecture is intentionally modular so the `future_features` on the
roadmap (Word→PDF, Merge, Split, OCR, Compression, Watermark, batch
conversion, accounts, history, premium plans, dark mode, i18n) can be
added as additional `api/*.php` endpoints + `scripts/*.py` workers without
touching the existing conversion flow. `JobManager` and `Config` are
generic enough to be reused for any file-in/file-out background job.
