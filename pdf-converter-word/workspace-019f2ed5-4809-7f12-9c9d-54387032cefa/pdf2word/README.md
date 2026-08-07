# DocuSwift — PDF to Word Converter

## Project Overview

DocuSwift is a lightweight web application that converts PDF documents into
editable Microsoft Word files (DOCX). The service is implemented as a
self-hosted application using a static frontend, a PHP backend, and a Python
conversion worker.

This project is intended for developers, educators, and teams who need a
simple PDF-to-Word conversion service without relying on external APIs.

## Features

- Drag-and-drop PDF upload with file picker fallback.
- PDF validation for extension, real MIME type, and file signature.
- Asynchronous, non-blocking conversion using a Python worker.
- Jobs are polled for progress and reported back to the frontend.
- Single-use DOCX download that removes converted artifacts after delivery.
- Temporary storage cleanup by retention time and optional cron job.
- Rate limiting to prevent rapid repeated requests.
- Local PHP configuration support for large uploads.

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, Vanilla JavaScript (ES6 modules) |
| Backend | PHP 8+ |
| Conversion | Python 3, `pdf2docx` |
| Storage | Filesystem-based upload, converted, and log folders |
| Deployment | PHP built-in server, Apache, Nginx |

## Architecture

The application separates concerns into three layers:

- **Frontend**: `index.html` with UI scripts under `assets/js/` to handle
  file selection, upload, status polling, and download linking.
- **Backend**: PHP API endpoints in `api/` manage upload validation, job
  creation, status querying, and file download.
- **Worker**: `scripts/convert.py` performs PDF → DOCX conversion and writes
  status updates to disk.

Uploads are accepted immediately and converted in the background. The
frontend polls `api/status.php` until the worker is finished.

## Folder Structure

| Path | Description |
|---|---|
| `api/` | Backend API endpoints (`csrf.php`, `upload.php`, `status.php`, `download.php`) |
| `assets/` | Frontend assets including CSS and JS |
| `includes/` | Shared PHP classes and bootstrap logic |
| `scripts/` | Conversion worker and cleanup script |
| `uploads/` | Stored incoming PDF files |
| `converted/` | Generated DOCX files |
| `logs/` | Application logs and rate limiter state |
| `deploy/` | Example web server configuration files |
| `requirements.txt` | Python dependency list |
| `.user.ini` | Local PHP runtime upload limit overrides |
| `php.ini` | Local PHP runtime upload limit overrides |
| `verify_sample_conversion.py` | End-to-end verification helper script |

## Prerequisites

- PHP 8 or newer.
- Python 3.
- `pip` or an equivalent Python package manager.
- A web server or PHP built-in server for local testing.

## Installation

From the `pdf2word/` directory, install the Python dependency:

```bash
python -m pip install -r requirements.txt
```

If you need to point PHP at a specific Python interpreter, set:

```bash
export PDF2WORD_PYTHON_BIN=/path/to/python
```

On Windows PowerShell:

```powershell
$env:PDF2WORD_PYTHON_BIN = 'C:\Python314\python.exe'
```

## Running the Project

### Local development

Start the local PHP server from `pdf2word/`:

```bash
php -c php.ini -S 127.0.0.1:8000
```

Open the app at:

```text
http://127.0.0.1:8000/index.html
```

### Alternative PHP configuration

The project includes local PHP overrides in `.user.ini` and `php.ini`.
These files set upload and POST limits for large files:

```ini
upload_max_filesize = 100M
post_max_size = 105M
memory_limit = 256M
max_execution_time = 300
max_input_time = 300
```

If the local server does not use these files automatically, ensure the
PHP process is started with a configuration file that includes these values.

## Configuration

### `includes/Config.php`

The primary application settings are stored here, including:

- `maxUploadBytes()` — upload limit (100MB)
- `allowedExtensions()` — allowed upload extensions (`pdf`)
- `allowedMimeTypes()` — allowed MIME types (`application/pdf`)
- `retentionMinutes()` — file retention window (30 minutes)
- `jobTimeoutSeconds()` — worker status timeout (300 seconds)
- `pythonBinary()` — Python interpreter, overridable with `PDF2WORD_PYTHON_BIN`

### Local PHP runtime config

The repository includes both `.user.ini` and `php.ini` for local PHP
upload limit overrides. These are not a substitute for a production PHP
configuration, but they are intended to make local testing easier.

## Usage

1. Open the application in a browser.
2. Drag and drop a PDF file or select one using the file picker.
3. The frontend uploads the file and shows upload/conversion progress.
4. When conversion completes, click the download button to retrieve the
   generated DOCX file.

The UI performs client-side checks for PDF extension, MIME type, and
maximum file size before uploading.

## Conversion Workflow

1. The browser requests a CSRF token from `api/csrf.php`.
2. The file is uploaded to `api/upload.php` with the CSRF token.
3. `FileValidator.php` verifies the upload and saves the PDF under a
   random filename.
4. `JobManager::createJob()` writes job metadata and launches the Python
   conversion worker via `proc_open()`.
5. The worker in `scripts/convert.py` converts the PDF and writes status
   JSON to the uploads directory.
6. The frontend polls `api/status.php` until the job state is `done` or
   `error`.
7. The user downloads the converted DOCX from `api/download.php`.
8. `api/download.php` streams the file and immediately purges the job
   artifacts.

## Error Handling

Common failure modes and resolutions:

- **Upload limit exceeded**: ensure the active PHP process is using
  `upload_max_filesize = 100M` and `post_max_size = 105M`.
- **Invalid PDF**: `FileValidator.php` rejects files that are not PDF by
  extension, MIME type, or magic byte header.
- **Missing `fileinfo` extension**: the validator can fall back to a
  header check, but enabling `fileinfo` is recommended.
- **Worker failure**: inspect `logs/worker-*.log` for Python conversion
  errors.
- **Rate limit**: uploads are limited to 20 requests per IP per 10
  minutes.

## Security

- CSRF protection is enforced for upload requests.
- Uploaded files are stored with random identifiers.
- Original filenames are sanitized and only used for download.
- Internal directories are protected by `.htaccess` and example server
  configuration.
- `proc_open()` uses `bypass_shell => true` to avoid shell execution.
- API errors are returned as JSON and do not expose stack traces.

## Performance Notes

- Conversion is asynchronous; upload requests do not wait for completion.
- The worker may take longer for large or complex PDFs.
- Status polling uses a lightweight API endpoint every ~1.2 seconds.
- Cleanup can be run via `scripts/cleanup.php` to remove expired files.
- Logs are written in JSON lines to `logs/app-YYYY-MM-DD.log`.

## Future Improvements

These changes would fit naturally into the existing architecture:

- Add OCR support for scanned PDFs.
- Support batch or multi-file conversion jobs.
- Add user accounts, conversion history, or job management.
- Replace file-based state with a queue-backed worker system.
- Add more robust upload retries and resumable upload support.

## Contributing

1. Fork the repository.
2. Create a branch for your feature or fix.
3. Install dependencies and run the application locally.
4. Test your changes with the frontend and the Python worker.
5. Submit a pull request with a clear description of the change.

## License

No `LICENSE` file is included in the repository. Add a license file to
define reuse terms before publishing or distributing the project.
