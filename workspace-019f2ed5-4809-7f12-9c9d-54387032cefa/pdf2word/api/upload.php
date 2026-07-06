<?php
/**
 * POST /api/upload.php
 * ---------------------------------------------------------------
 * Accepts a single PDF (multipart/form-data, field name "file"),
 * validates it, stores it under a random name and starts an
 * asynchronous conversion job. Responds immediately with a jobId
 * that the frontend polls via status.php.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

require_once __DIR__ . '/../includes/bootstrap.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Response::error('Method not allowed.', 405);
}

if (!RateLimiter::allow(Security::clientIp())) {
    Response::error('Too many requests. Please wait a moment and try again.', 429);
}

$csrfToken = $_SERVER['HTTP_X_CSRF_TOKEN'] ?? ($_POST['csrf_token'] ?? null);
if (!Security::verifyCsrfToken($csrfToken)) {
    Response::error('Invalid or expired security token. Please reload the page.', 403);
}

if (!isset($_FILES['file'])) {
    Response::error('No file was uploaded.', 400);
}

$validation = FileValidator::validateUpload($_FILES['file']);
if (!$validation['valid']) {
    Response::error($validation['error'], 422);
}

try {
    $job = JobManager::createJob($_FILES['file']);
} catch (Throwable $e) {
    Logger::error('Upload failed', ['message' => $e->getMessage()]);
    Response::error('We could not process your upload. Please try again.', 500);
}

Response::success(['jobId' => $job['jobId']], 202);
