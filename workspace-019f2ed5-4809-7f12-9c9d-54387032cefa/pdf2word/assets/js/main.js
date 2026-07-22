/**
 * main.js
 * ---------------------------------------------------------------
 * Application entry point. Orchestrates the full conversion flow:
 *   select/drop file -> validate -> upload -> poll status -> download
 * ---------------------------------------------------------------
 */

import { fetchCsrfToken, uploadFile, fetchStatus, downloadUrl } from './api.js';
import { showState, formatFileSize, setProgress, initMobileNav } from './ui.js';
import { initThemeToggle } from './theme.js';
import { initScrollReveal, initNavbarScrollShadow, initCounters } from './scroll-effects.js';

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB, mirrors backend Config::maxUploadBytes()
const POLL_INTERVAL_MS = 1200;

let csrfToken = null;
let activeJobId = null;
let pollTimer = null;

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const fileNameEl = document.getElementById('fileName');
const fileSizeEl = document.getElementById('fileSize');
const removeFileBtn = document.getElementById('removeFileBtn');
const downloadBtn = document.getElementById('downloadBtn');
const doneFileNameEl = document.getElementById('doneFileName');
const convertAnotherBtn = document.getElementById('convertAnotherBtn');
const tryAgainBtn = document.getElementById('tryAgainBtn');
const errorMessageEl = document.getElementById('errorMessage');

/** Resets the widget back to the initial drop-zone state. */
function resetToIdle() {
  stopPolling();
  activeJobId = null;
  fileInput.value = '';
  showState('stateIdle');
  setProgress(0, 'Uploading your document...');
}

function showError(message) {
  stopPolling();
  errorMessageEl.textContent = message || 'Something went wrong. Please try again.';
  showState('stateError');
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

/** Client-side pre-flight checks, mirroring backend validation for instant feedback. */
function validateFile(file) {
  const isPdfExtension = /\.pdf$/i.test(file.name);
  const isPdfMime = file.type === 'application/pdf' || file.type === '';

  if (!isPdfExtension || !isPdfMime) {
    return 'Only PDF files are supported.';
  }
  if (file.size > MAX_FILE_SIZE) {
    return 'The file exceeds the 100MB size limit.';
  }
  if (file.size <= 0) {
    return 'The selected file is empty.';
  }
  return null;
}

async function handleFile(file) {
  const validationError = validateFile(file);
  if (validationError) {
    showError(validationError);
    return;
  }

  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatFileSize(file.size);
  showState('stateProgress');
  setProgress(5, 'Uploading your document...');

  try {
    if (!csrfToken) {
      csrfToken = await fetchCsrfToken();
    }

    const { jobId } = await uploadFile(file, csrfToken);
    activeJobId = jobId;
    pollStatus();
  } catch (err) {
    showError(err.message);
  }
}

/** Polls /api/status.php until the job is done, errors, or is not found. */
async function pollStatus() {
  if (!activeJobId) return;

  try {
    const status = await fetchStatus(activeJobId);

    if (status.state === 'error') {
      showError(status.message);
      return;
    }

    if (status.state === 'done') {
      setProgress(100, status.message);
      doneFileNameEl.textContent = (status.originalName || 'document').replace(/\.pdf$/i, '.docx');
      downloadBtn.href = downloadUrl(activeJobId);
      showState('stateDone');
      return;
    }

    // queued or processing: keep polling
    setProgress(status.progress ?? 0, status.message);
    pollTimer = setTimeout(pollStatus, POLL_INTERVAL_MS);
  } catch (err) {
    showError(err.message);
  }
}

/* ------------------------------ Event wiring ------------------------------ */

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    fileInput.click();
  }
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) {
    handleFile(fileInput.files[0]);
  }
});

['dragenter', 'dragover'].forEach((eventName) => {
  dropzone.addEventListener(eventName, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add('is-dragover');
  });
});

['dragleave', 'drop'].forEach((eventName) => {
  dropzone.addEventListener(eventName, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove('is-dragover');
  });
});

dropzone.addEventListener('drop', (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) handleFile(file);
});

Dropzone.options.dropzone = { // Make sure 'myDropzone' matches your HTML form ID
    url: "upload.php", 
    paramName: "file", 
    maxFilesize: 10, // MB
    acceptedFiles: ".pdf",
    dictDefaultMessage: "Drop your PDF here to upload",
    init: function() {
        this.on("success", function(file, response) {
            console.log("Server Response:", response);
            alert("File uploaded successfully! (Conversion simulation)");
            // If you have a download button, you can make it appear here using response.download_url
        });
        this.on("error", function(file, message) {
            console.error("Upload Error:", message);
            alert("Error: " + (message.error || "Unexpected server response"));
        });
    }
};
removeFileBtn.addEventListener('click', resetToIdle);
convertAnotherBtn.addEventListener('click', resetToIdle);
tryAgainBtn.addEventListener('click', resetToIdle);

// After the user actually downloads the file, return the widget to idle
// so a repeat conversion feels fresh rather than stuck on the success state.
downloadBtn.addEventListener('click', () => {
  setTimeout(resetToIdle, 800);
});

document.getElementById('year').textContent = new Date().getFullYear();

initMobileNav();
initThemeToggle();
initScrollReveal();
initNavbarScrollShadow();
initCounters();
