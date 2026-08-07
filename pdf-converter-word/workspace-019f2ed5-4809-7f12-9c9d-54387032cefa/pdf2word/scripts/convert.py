#!/usr/bin/env python3
"""
convert.py
------------------------------------------------------------------
Standalone PDF -> DOCX conversion worker used by the PHP backend.

Usage:
    python3 convert.py <input.pdf> <output.docx> <status_json_path>

The script writes structured JSON status updates to <status_json_path>
so the PHP layer (and the browser, via polling) can report granular
progress ("Analyzing pages...", "Extracting text...", etc.) even
though pdf2docx itself only exposes a single blocking call.

Exit codes:
    0  -> success
    1  -> bad arguments
    2  -> input file missing / unreadable
    3  -> conversion failed
------------------------------------------------------------------
"""

import sys
import os
import json
import time
import traceback

# Page count above which we switch to a coarser progress simulation
# (fine-grained page-by-page progress would slow down small files).
LARGE_DOC_PAGE_THRESHOLD = 30


def write_status(status_path, payload):
    """Atomically write the progress/status JSON file."""
    tmp_path = status_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp_path, status_path)


def main():
    if len(sys.argv) != 4:
        print("Usage: convert.py <input.pdf> <output.docx> <status_json_path>", file=sys.stderr)
        sys.exit(1)

    input_pdf, output_docx, status_path = sys.argv[1], sys.argv[2], sys.argv[3]

    if not os.path.isfile(input_pdf):
        write_status(status_path, {
            "state": "error",
            "message": "Input file not found.",
            "progress": 0,
        })
        sys.exit(2)

    write_status(status_path, {
        "state": "processing",
        "message": "Analyzing pages...",
        "progress": 10,
    })

    try:
        # Imported lazily so argument/file errors above fail fast without
        # paying the (relatively) expensive import cost of pdf2docx/fitz.
        from pdf2docx import Converter
        import fitz  # PyMuPDF, bundled as a dependency of pdf2docx

        # Quick page count for progress estimation + sanity validation
        # that the file is really a parsable PDF (not just an extension).
        try:
            doc = fitz.open(input_pdf)
            page_count = doc.page_count
            doc.close()
        except Exception:
            write_status(status_path, {
                "state": "error",
                "message": "The uploaded file is not a valid PDF.",
                "progress": 0,
            })
            sys.exit(3)

        write_status(status_path, {
            "state": "processing",
            "message": "Extracting text and layout...",
            "progress": 35,
            "pages": page_count,
        })

        cv = Converter(input_pdf)

        write_status(status_path, {
            "state": "processing",
            "message": "Building Word document...",
            "progress": 65,
            "pages": page_count,
        })

        cv.convert(output_docx, start=0, end=None)
        cv.close()

        write_status(status_path, {
            "state": "processing",
            "message": "Almost finished...",
            "progress": 90,
            "pages": page_count,
        })

        if not os.path.isfile(output_docx) or os.path.getsize(output_docx) == 0:
            raise RuntimeError("Converter did not produce an output file.")

        write_status(status_path, {
            "state": "done",
            "message": "Your Word document is ready.",
            "progress": 100,
            "pages": page_count,
        })
        sys.exit(0)

    except Exception as exc:  # noqa: BLE001 - report any failure to PHP layer
        write_status(status_path, {
            "state": "error",
            "message": "Conversion failed. Please try again with a different file.",
            "progress": 0,
            "detail": str(exc),
        })
        traceback.print_exc(file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
