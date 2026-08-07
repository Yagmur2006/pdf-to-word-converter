#!/usr/bin/env python3
"""
pdf2word - Online PDF to Word Converter (async architecture).

Conversion engine: **pdf2docx** (unchanged).
Everything around it has been rebuilt:

  * ``POST /convert`` validates + enqueues and returns a ``job_id`` in
    milliseconds. It never blocks on conversion.
  * CPU work runs in a ``ProcessPoolExecutor`` (page chunks + files in
    parallel), a ``ThreadPoolExecutor`` orchestrates each job.
  * ``GET /status/<job_id>`` exposes real per-file / per-page progress for
    frontend polling.
  * ``GET /download/<job_id>[/<file_id>]`` streams the DOCX or ZIP with the
    original Persian / Unicode filename intact.
  * Hard limits on file size, batch size and page count reject pathological
    uploads before any work starts.
  * A background sweeper deletes temp artefacts on TTL, download or shutdown.
"""

from __future__ import annotations

import atexit
import logging
import math
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import (
    CancelledError,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from converter_worker import (
    DEFAULT_QUALITY,
    QUALITY_PROFILES,
    build_docx,
    build_settings,
    init_worker,
    parse_chunk,
    plan_chunks,
    preload,
    probe_pdf,
    warmup,
)

# ---------------------------------------------------------------------------
# Limits & tuning
# ---------------------------------------------------------------------------
MB = 1024 * 1024

MAX_BATCH_BYTES = 100 * MB       # hard ceiling enforced by Werkzeug
MAX_FILE_BYTES = 50 * MB         # per-file ceiling
MAX_FILES_PER_BATCH = 20
MAX_PAGES_PER_FILE = 300
MAX_PAGES_PER_BATCH = 800

PAGES_PER_CHUNK = 3              # granularity of parallel page parsing - small
                                  # chunks keep every core fed instead of a few
                                  # workers finishing early and sitting idle.
JOB_TIMEOUT_SECONDS = 900        # 15 min hard stop per job
JOB_TTL_SECONDS = 30 * 60        # keep finished jobs for 30 min
JOB_TTL_AFTER_DOWNLOAD = 3 * 60  # ...or 3 min once downloaded
SWEEP_INTERVAL_SECONDS = 60

CPU_TOTAL = os.cpu_count() or 2
# Use every available core: Flask/Node only do light I/O while a conversion
# runs, so nothing meaningful is lost by not reserving a core for them.
PROCESS_WORKERS = max(2, CPU_TOTAL)
MAX_CHUNKS_PER_FILE = PROCESS_WORKERS * 3
ORCHESTRATOR_THREADS = 8

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pdf2word")
logging.getLogger("pdf2docx").setLevel(logging.ERROR)

IS_MAIN_PROCESS = multiprocessing.current_process().name == "MainProcess"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BATCH_BYTES
app.config["JSON_AS_ASCII"] = False


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------
# 'fork' is what pdf2docx itself uses internally, and it lets workers inherit
# the already-imported pdf2docx/PyMuPDF stack (see `preload`) instead of paying
# a multi-second import per worker. The pool is created and fully populated
# during bootstrap - before Flask starts serving and before any request thread
# exists - which is what makes forking safe here.
default_mp_method = "spawn" if os.name == "nt" else "fork"
_MP_START_METHOD = os.environ.get("PDF2WORD_MP_START", default_mp_method)
_MP_CONTEXT = multiprocessing.get_context(_MP_START_METHOD)

process_pool: ProcessPoolExecutor | None = None
orchestrator: ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _start_executors() -> None:
    global process_pool, orchestrator
    with _POOL_LOCK:
        if process_pool is not None:
            return
        # Import the heavy stack first so forked children inherit it.
        preload()
        process_pool = ProcessPoolExecutor(
            max_workers=PROCESS_WORKERS,
            mp_context=_MP_CONTEXT,
            initializer=init_worker,
        )
        if orchestrator is None:
            orchestrator = ThreadPoolExecutor(
                max_workers=ORCHESTRATOR_THREADS,
                thread_name_prefix="job",
            )
        log.info(
            "Executors ready: %d conversion processes (%s), %d orchestrator threads",
            PROCESS_WORKERS,
            _MP_START_METHOD,
            ORCHESTRATOR_THREADS,
        )


def _reset_pool() -> None:
    """Rebuild the pool after a worker crash (BrokenProcessPool)."""
    global process_pool
    with _POOL_LOCK:
        old, process_pool = process_pool, None
    if old is not None:
        old.shutdown(wait=False, cancel_futures=True)
    _start_executors()
    log.warning("Process pool was rebuilt after a worker crash")


def _warm_pool() -> None:
    """Force every worker process to exist before the first user request."""
    try:
        assert process_pool is not None
        futures = [process_pool.submit(warmup) for _ in range(PROCESS_WORKERS)]
        for future in futures:
            future.result(timeout=120)
        log.info("Process pool warmed up (%d workers)", PROCESS_WORKERS)
    except Exception as exc:  # pragma: no cover
        log.warning("Pool warmup skipped: %s", exc)


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_PARTIAL, STATUS_FAILED, STATUS_CANCELLED}


def _touch(job: dict[str, Any]) -> None:
    job["updated_at"] = time.time()


# Page parsing is the parallel phase; `make_docx` is inherently serial per
# document and, on table-heavy PDFs, costs more than parsing. The bar reserves
# a large slice for assembly and eases into it on an exponential curve, so it
# always keeps creeping forward even when the time estimate is wrong.
PARSE_WEIGHT = 60
BUILD_TAU_FACTOR = 0.6  # tau ~= 0.6 * (sequential-equivalent parse time)


def _file_progress(entry: dict[str, Any]) -> int:
    """Live progress for one file, 0-100."""
    if entry["status"] in ("done", "error"):
        return 100

    total = max(1, entry["total_chunks"])
    parsed = min(entry["parsed_chunks"], total)
    progress = parsed / total * PARSE_WEIGHT

    if entry["status"] == "processing" and not entry.get("building"):
        # Ease across the *current* chunk's band so the bar is alive even
        # while the very first chunk is still being parsed.
        band = PARSE_WEIGHT / total
        elapsed = time.time() - entry.get("parse_started", time.time())
        progress += band * (1.0 - math.exp(-elapsed / 6.0))

    if entry.get("building") and entry.get("build_started"):
        # Parsing ran on `total` cores, so multiply the wall time back up to
        # estimate the single-threaded work that assembly is proportional to.
        sequential_parse = max(0.5, entry.get("parse_seconds", 1.0)) * total
        tau = max(1.5, sequential_parse * BUILD_TAU_FACTOR)
        elapsed = time.time() - entry["build_started"]
        # 1 - e^(-t/tau): 63% of the band at tau, 86% at 2*tau, never stalls
        # and never reaches 100 before the worker actually reports back.
        ratio = 1.0 - math.exp(-elapsed / tau)
        progress = PARSE_WEIGHT + (99 - PARSE_WEIGHT) * ratio

    return int(min(99, progress))


def _recalculate_progress(job: dict[str, Any]) -> None:
    """Overall progress = page-weighted mean of live per-file progress."""
    files = job["files"]
    if not files:
        job["progress"] = 0
        return
    for entry in files:
        entry["progress"] = _file_progress(entry)
    total_weight = sum(max(1, f["pages"]) for f in files)
    done = sum(f["progress"] * max(1, f["pages"]) for f in files)
    job["progress"] = int(min(100, round(done / total_weight)))


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = job["id"]
    # Recompute on read so the build phase keeps advancing between polls.
    if job["status"] not in TERMINAL_STATUSES:
        _recalculate_progress(job)
    files = []
    for entry in job["files"]:
        files.append(
            {
                "id": entry["id"],
                "name": entry["display_name"],
                "source_name": entry["original_name"],
                "size": entry["size"],
                "pages": entry["pages"],
                "status": entry["status"],
                "progress": entry["progress"],
                "error": entry["error"],
                "download_url": (
                    f"/download/{job_id}/{entry['id']}"
                    if entry["status"] == "done"
                    else None
                ),
            }
        )

    succeeded = [f for f in job["files"] if f["status"] == "done"]
    return {
        "job_id": job_id,
        "status": job["status"],
        "phase": job["phase"],
        "progress": job["progress"],
        "error": job["error"],
        "quality": job["quality"],
        "file_count": len(job["files"]),
        "succeeded": len(succeeded),
        "failed": len([f for f in job["files"] if f["status"] == "error"]),
        "elapsed": round(time.time() - job["created_at"], 1),
        "files": files,
        "download_url": f"/download/{job_id}" if succeeded else None,
        "is_zip": len(succeeded) > 1,
    }


def _destroy_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = JOBS.pop(job_id, None)
    if not job:
        return
    temp_dir = job.get("temp_dir")
    if temp_dir and os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    log.info("Job %s cleaned up", job_id)


def _sweeper() -> None:
    """Delete abandoned / expired jobs and their temp directories."""
    while True:
        time.sleep(SWEEP_INTERVAL_SECONDS)
        now = time.time()
        expired: list[str] = []
        with JOBS_LOCK:
            for job_id, job in JOBS.items():
                age = now - job["created_at"]
                downloaded_at = job.get("downloaded_at")
                if downloaded_at and now - downloaded_at > JOB_TTL_AFTER_DOWNLOAD:
                    expired.append(job_id)
                elif age > JOB_TTL_SECONDS:
                    expired.append(job_id)
        for job_id in expired:
            _destroy_job(job_id)


@atexit.register
def _shutdown() -> None:  # pragma: no cover
    with JOBS_LOCK:
        job_ids = list(JOBS.keys())
    for job_id in job_ids:
        _destroy_job(job_id)
    if process_pool is not None:
        process_pool.shutdown(wait=False, cancel_futures=True)
    if orchestrator is not None:
        orchestrator.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------
def _run_job(job_id: str) -> None:
    """Orchestrate one job. Runs on an orchestrator thread, never on a request."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = STATUS_PROCESSING
        job["phase"] = "Parsing pages"
        _touch(job)

    overrides = build_settings(job["quality"])
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    _start_executors()
    assert process_pool is not None
    pool = process_pool
    pool_broken = False

    parse_futures: dict[Future, tuple[dict[str, Any], int]] = {}
    build_futures: dict[Future, dict[str, Any]] = {}

    def cancelled() -> bool:
        with JOBS_LOCK:
            return bool(job.get("cancel_requested"))

    def fail_file(entry: dict[str, Any], message: str) -> None:
        with JOBS_LOCK:
            entry["status"] = "error"
            entry["error"] = message
            entry["progress"] = 100
            _recalculate_progress(job)
            _touch(job)

    def maybe_submit_build(entry: dict[str, Any]) -> None:
        """Once every chunk of a file is parsed, assemble its docx."""
        if entry["status"] == "error" or entry["parsed_chunks"] < entry["total_chunks"]:
            return
        with JOBS_LOCK:
            entry["building"] = True
            entry["build_started"] = time.time()
            entry["parse_seconds"] = max(
                0.5, entry["build_started"] - entry["parse_started"]
            )
            _recalculate_progress(job)
            job["phase"] = "Building Word documents"
            _touch(job)
        future = pool.submit(
            build_docx,
            entry["pdf_path"],
            entry["json_paths"],
            entry["docx_path"],
            overrides,
        )
        build_futures[future] = entry

    try:
        # ---- Stage 1: every page chunk of every file, all in parallel ------
        for entry in job["files"]:
            for index, page_indexes in enumerate(entry["chunks"]):
                json_path = os.path.join(
                    job["temp_dir"], f"{entry['id']}-chunk{index}.json"
                )
                entry["json_paths"].append(json_path)
                future = pool.submit(
                    parse_chunk, entry["pdf_path"], page_indexes, json_path, overrides
                )
                parse_futures[future] = (entry, index)

        started_at = time.time()
        with JOBS_LOCK:
            for entry in job["files"]:
                entry["status"] = "processing"
                entry["parse_started"] = started_at
            _touch(job)

        for future in as_completed(list(parse_futures), timeout=max(1, deadline - time.time())):
            entry, _index = parse_futures[future]
            if cancelled():
                break
            try:
                future.result()
            except CancelledError:
                break
            except Exception as exc:
                log.exception("Parse failure in job %s", job_id)
                if isinstance(exc, BrokenProcessPool):
                    pool_broken = True
                fail_file(entry, _friendly_error(exc))
                continue

            with JOBS_LOCK:
                entry["parsed_chunks"] += 1
                entry["progress"] = _file_progress(entry)
                _recalculate_progress(job)
                _touch(job)
            maybe_submit_build(entry)

        if cancelled():
            raise _JobCancelled()

        # ---- Stage 2: docx assembly ---------------------------------------
        if build_futures:
            for future in as_completed(list(build_futures), timeout=max(1, deadline - time.time())):
                entry = build_futures[future]
                if cancelled():
                    break
                try:
                    future.result()
                except CancelledError:
                    break
                except Exception as exc:
                    log.exception("Build failure in job %s", job_id)
                    if isinstance(exc, BrokenProcessPool):
                        pool_broken = True
                    fail_file(entry, _friendly_error(exc))
                    continue

                with JOBS_LOCK:
                    entry["building"] = False
                    if os.path.exists(entry["docx_path"]) and os.path.getsize(entry["docx_path"]) > 0:
                        entry["status"] = "done"
                        entry["progress"] = 100
                    else:
                        entry["status"] = "error"
                        entry["error"] = "Converter produced an empty document."
                        entry["progress"] = 100
                    _recalculate_progress(job)
                    _touch(job)

        if cancelled():
            raise _JobCancelled()

        # ---- Stage 3: bundle ----------------------------------------------
        succeeded = [f for f in job["files"] if f["status"] == "done"]
        if len(succeeded) > 1:
            with JOBS_LOCK:
                job["phase"] = "Packaging ZIP"
                _touch(job)
            job["zip_path"] = _make_zip(job, succeeded)

        with JOBS_LOCK:
            if not succeeded:
                job["status"] = STATUS_FAILED
                job["phase"] = "Failed"
                job["error"] = job["files"][0]["error"] if job["files"] else "Conversion failed."
            elif len(succeeded) < len(job["files"]):
                job["status"] = STATUS_PARTIAL
                job["phase"] = "Completed with errors"
            else:
                job["status"] = STATUS_COMPLETED
                job["phase"] = "Completed"
            job["progress"] = 100
            _touch(job)

        log.info(
            "Job %s finished: %s (%d/%d files, %.1fs)",
            job_id,
            job["status"],
            len(succeeded),
            len(job["files"]),
            time.time() - job["created_at"],
        )

    except _JobCancelled:
        for future in list(parse_futures) + list(build_futures):
            future.cancel()
        with JOBS_LOCK:
            job["status"] = STATUS_CANCELLED
            job["phase"] = "Cancelled"
            job["error"] = "Conversion cancelled."
            _touch(job)
        log.info("Job %s cancelled", job_id)

    except FuturesTimeoutError:
        for future in list(parse_futures) + list(build_futures):
            future.cancel()
        with JOBS_LOCK:
            job["status"] = STATUS_FAILED
            job["phase"] = "Timed out"
            job["error"] = (
                f"Conversion exceeded the {JOB_TIMEOUT_SECONDS // 60} minute limit. "
                "Try 'Fast' mode or a smaller document."
            )
            job["progress"] = 100
            _touch(job)
        log.warning("Job %s timed out", job_id)

    except Exception as exc:  # pragma: no cover
        log.exception("Job %s crashed", job_id)
        if isinstance(exc, BrokenProcessPool):
            pool_broken = True
        with JOBS_LOCK:
            job["status"] = STATUS_FAILED
            job["phase"] = "Failed"
            job["error"] = _friendly_error(exc)
            job["progress"] = 100
            _touch(job)

    finally:
        # PDFs are useless once parsed - reclaim the disk immediately.
        for entry in job["files"]:
            try:
                os.remove(entry["pdf_path"])
            except OSError:
                pass
        if pool_broken:
            _reset_pool()


class _JobCancelled(Exception):
    """Internal control-flow signal."""


def _friendly_error(exc: BaseException) -> str:
    """Map internal exceptions onto clean, user-facing messages."""
    name = type(exc).__name__
    text = str(exc).strip() or name

    if isinstance(exc, MemoryError) or "MemoryError" in name:
        return (
            "The server ran out of memory for this document. "
            "Try 'Fast' mode or split the PDF."
        )
    if "BrokenProcessPool" in name or "BrokenExecutor" in name:
        return (
            "A conversion worker crashed on this document - it may be corrupted "
            "or use an unsupported feature."
        )
    if "password" in text.lower() or "encrypt" in text.lower():
        return "This PDF is password protected and cannot be converted."
    if len(text) > 220:
        text = text[:217] + "..."
    return text


def _make_zip(job: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    """Bundle converted DOCX files, keeping original Unicode names unique."""
    zip_path = os.path.join(job["temp_dir"], "converted_documents.zip")
    used: dict[str, int] = {}

    # DOCX is already a compressed container, so ZIP_STORED is both faster and
    # produces near-identical size compared to re-deflating.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as archive:
        for entry in entries:
            name = entry["display_name"]
            if name in used:
                used[name] += 1
                stem, ext = os.path.splitext(name)
                name = f"{stem} ({used[name]}){ext}"
            else:
                used[name] = 0
            archive.write(entry["docx_path"], arcname=name)
    return zip_path


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _stream_size(stream) -> int:
    position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(position)
    return size


def _human(num_bytes: int) -> str:
    return f"{num_bytes / MB:.0f}MB"


def _error(message: str, status: int = 400, **extra: Any):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/health", methods=["GET"])
@app.route("/api/health", methods=["GET"])
def health():
    with JOBS_LOCK:
        active = sum(1 for j in JOBS.values() if j["status"] not in TERMINAL_STATUSES)
        total = len(JOBS)
    return jsonify(
        {
            "status": "ok",
            "workers": PROCESS_WORKERS,
            "active_jobs": active,
            "tracked_jobs": total,
        }
    )


@app.route("/limits", methods=["GET"])
def limits():
    return jsonify(
        {
            "max_batch_bytes": MAX_BATCH_BYTES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_files": MAX_FILES_PER_BATCH,
            "max_pages_per_file": MAX_PAGES_PER_FILE,
            "max_pages_per_batch": MAX_PAGES_PER_BATCH,
            "qualities": list(QUALITY_PROFILES.keys()),
            "default_quality": DEFAULT_QUALITY,
        }
    )


@app.route("/convert", methods=["POST"])
def convert():
    """Validate + enqueue. Returns 202 with a job id; never blocks."""
    _start_executors()

    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]

    if not files:
        return _error("No files provided.")
    if len(files) > MAX_FILES_PER_BATCH:
        return _error(
            f"Too many files: {len(files)}. Maximum is {MAX_FILES_PER_BATCH} per batch."
        )

    quality = (request.form.get("quality") or DEFAULT_QUALITY).lower()
    if quality not in QUALITY_PROFILES:
        quality = DEFAULT_QUALITY

    # --- cheap validation before touching the disk -------------------------
    total_bytes = 0
    for storage in files:
        if not storage.filename.lower().endswith(".pdf"):
            return _error(
                f'"{storage.filename}" is not a PDF. Only .pdf files are supported.'
            )
        size = _stream_size(storage.stream)
        if size == 0:
            return _error(f'"{storage.filename}" is empty.')
        if size > MAX_FILE_BYTES:
            return _error(
                f'"{storage.filename}" is {size / MB:.1f}MB. '
                f"The per-file limit is {_human(MAX_FILE_BYTES)}."
            )
        total_bytes += size

    if total_bytes > MAX_BATCH_BYTES:
        return _error(
            f"Batch is {total_bytes / MB:.1f}MB. The limit is {_human(MAX_BATCH_BYTES)}."
        )

    job_id = uuid.uuid4().hex
    temp_dir = tempfile.mkdtemp(prefix=f"pdf2word-{job_id[:8]}-")
    entries: list[dict[str, Any]] = []
    total_pages = 0
    now_ts = time.time()

    # With a single upload we split its pages across every core. With a big
    # batch, cross-file parallelism already saturates the pool, so each file
    # stays in one chunk and avoids redundant per-chunk document analysis.
    min_chunks = max(1, -(-PROCESS_WORKERS // len(files)))

    try:
        for storage in files:
            original_name = storage.filename
            file_id = uuid.uuid4().hex[:12]

            # UUID paths on disk: Persian / Arabic / CJK names never touch the
            # filesystem, so no encoding crash is possible. The Unicode name is
            # kept in memory purely for the download response.
            pdf_path = os.path.join(temp_dir, f"{file_id}.pdf")
            docx_path = os.path.join(temp_dir, f"{file_id}.docx")
            storage.save(pdf_path)

            size = os.path.getsize(pdf_path)
            try:
                meta = probe_pdf(pdf_path)
            except ValueError as exc:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _error(f'"{original_name}": {exc}')

            pages = meta["pages"]
            if pages > MAX_PAGES_PER_FILE:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _error(
                    f'"{original_name}" has {pages} pages. '
                    f"The limit is {MAX_PAGES_PER_FILE} pages per file."
                )
            total_pages += pages
            if total_pages > MAX_PAGES_PER_BATCH:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _error(
                    f"This batch has more than {MAX_PAGES_PER_BATCH} pages in total. "
                    "Please convert it in smaller groups."
                )

            chunks = plan_chunks(
                pages, PAGES_PER_CHUNK, MAX_CHUNKS_PER_FILE, min_chunks
            )
            stem = os.path.splitext(original_name)[0] or "document"

            entries.append(
                {
                    "id": file_id,
                    "original_name": original_name,
                    "display_name": f"{stem}.docx",
                    "size": size,
                    "pages": pages,
                    "pdf_path": pdf_path,
                    "docx_path": docx_path,
                    "json_paths": [],
                    "chunks": chunks,
                    "total_chunks": len(chunks),
                    "parsed_chunks": 0,
                    "building": False,
                    "parse_started": now_ts,
                    "parse_seconds": 0.0,
                    "build_started": None,
                    "status": "queued",
                    "progress": 0,
                    "error": None,
                }
            )
    except RequestEntityTooLarge:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.exception("Upload handling failed")
        return _error(f"Could not read the uploaded files: {_friendly_error(exc)}", 500)

    now = time.time()
    job = {
        "id": job_id,
        "created_at": now,
        "updated_at": now,
        "status": STATUS_QUEUED,
        "phase": "Queued",
        "progress": 0,
        "error": None,
        "quality": quality,
        "temp_dir": temp_dir,
        "files": entries,
        "zip_path": None,
        "cancel_requested": False,
        "downloaded_at": None,
        "total_pages": total_pages,
    }

    with JOBS_LOCK:
        JOBS[job_id] = job

    assert orchestrator is not None
    orchestrator.submit(_run_job, job_id)

    log.info(
        "Job %s queued: %d file(s), %d page(s), quality=%s",
        job_id,
        len(entries),
        total_pages,
        quality,
    )
    return jsonify(_public_job(job)), 202


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return _error("Job not found or expired.", 404)
        return jsonify(_public_job(job))


@app.route("/cancel/<job_id>", methods=["POST", "DELETE"])
def cancel(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return _error("Job not found or expired.", 404)
        if job["status"] in TERMINAL_STATUSES:
            return jsonify(_public_job(job))
        job["cancel_requested"] = True
        job["phase"] = "Cancelling"
        _touch(job)
        return jsonify(_public_job(job))


@app.route("/download/<job_id>", methods=["GET"])
@app.route("/download/<job_id>/<file_id>", methods=["GET"])
def download(job_id: str, file_id: str | None = None):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return _error("Job not found or expired.", 404)
        if job["status"] not in TERMINAL_STATUSES:
            return _error("Conversion is still running.", 409)

        succeeded = [f for f in job["files"] if f["status"] == "done"]
        if not succeeded:
            return _error("Nothing was converted successfully.", 404)

        if file_id:
            entry = next((f for f in succeeded if f["id"] == file_id), None)
            if not entry:
                return _error("File not found in this job.", 404)
            target, name, mime = entry["docx_path"], entry["display_name"], DOCX_MIME
        elif len(succeeded) == 1:
            entry = succeeded[0]
            target, name, mime = entry["docx_path"], entry["display_name"], DOCX_MIME
        else:
            if not job.get("zip_path") or not os.path.exists(job["zip_path"]):
                job["zip_path"] = _make_zip(job, succeeded)
            target, name, mime = job["zip_path"], "converted_documents.zip", "application/zip"

        job["downloaded_at"] = time.time()

    if not os.path.exists(target):
        return _error("The converted file has already been cleaned up.", 410)

    # `download_name` keeps the original Persian / Unicode title; Flask emits a
    # RFC 5987 `filename*=UTF-8''...` header so browsers restore it verbatim.
    return send_file(target, as_attachment=True, download_name=name, mimetype=mime)


@app.route("/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id: str):
    with JOBS_LOCK:
        exists = job_id in JOBS
    if not exists:
        return _error("Job not found or expired.", 404)
    _destroy_job(job_id)
    return jsonify({"deleted": True, "job_id": job_id})


# ---------------------------------------------------------------------------
# Error handlers - always JSON for the API
# ---------------------------------------------------------------------------
@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_exc):
    return _error(
        f"Upload exceeds the {_human(MAX_BATCH_BYTES)} batch limit.", 413
    )


@app.errorhandler(HTTPException)
def handle_http_exception(exc: HTTPException):
    if request.path == "/" or request.path.startswith("/static"):
        return exc
    return _error(exc.description or exc.name, exc.code or 500)


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):  # pragma: no cover
    log.exception("Unhandled error on %s", request.path)
    return _error(_friendly_error(exc), 500)


# ---------------------------------------------------------------------------
# Bootstrap (guarded so 'spawn' workers re-importing this file stay inert)
# ---------------------------------------------------------------------------
if IS_MAIN_PROCESS:
    # Order matters: fork every worker while the process is still single
    # threaded, then start the background threads.
    _start_executors()
    _warm_pool()
    threading.Thread(target=_sweeper, name="job-sweeper", daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    # threaded=True so status polls stay responsive while uploads stream in.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
