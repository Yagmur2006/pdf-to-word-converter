<?php
/**
 * GET /api/status.php?jobId=...
 * ---------------------------------------------------------------
 * Polled by the frontend every ~1s while a conversion is in
 * progress. Returns the current state, a human-readable progress
 * message and a 0-100 progress percentage.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

require_once __DIR__ . '/../includes/bootstrap.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    Response::error('Method not allowed.', 405);
}

$jobId = $_GET['jobId'] ?? '';
if (!is_string($jobId) || !JobManager::isValidJobId($jobId)) {
    Response::error('Invalid job identifier.', 400);
}

$status = JobManager::getStatus($jobId);

if ($status['state'] === 'not_found') {
    Response::error($status['message'], 404);
}

Response::success($status);
