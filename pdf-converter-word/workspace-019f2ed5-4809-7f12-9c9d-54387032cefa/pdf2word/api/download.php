<?php
/**
 * GET /api/download.php?jobId=...
 * ---------------------------------------------------------------
 * Streams the finished DOCX to the browser with the original file
 * name (sanitized) and deletes the job artifacts immediately after
 * a successful download so no converted document lingers longer
 * than necessary.
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

$download = JobManager::getDownload($jobId);
if ($download === null) {
    Response::error('The requested file is not available. It may have expired.', 404);
}

$path = $download['path'];
$filename = $download['downloadName'];
$size = filesize($path);

header('Content-Description: File Transfer');
header('Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document');
header('Content-Disposition: attachment; filename="' . addslashes($filename) . '"');
header('Content-Transfer-Encoding: binary');
header('Content-Length: ' . (string) $size);
header('Cache-Control: no-store, no-cache, must-revalidate');
header('X-Content-Type-Options: nosniff');

// Flush any buffered output before streaming the binary payload.
while (ob_get_level() > 0) {
    ob_end_clean();
}

readfile($path);

// Files are single-use: remove them right after they are served.
JobManager::purgeJob($jobId);

exit;
