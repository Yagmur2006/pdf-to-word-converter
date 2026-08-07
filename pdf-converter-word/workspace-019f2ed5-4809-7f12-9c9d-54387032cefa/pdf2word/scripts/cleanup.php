#!/usr/bin/env php
<?php
/**
 * cleanup.php
 * ---------------------------------------------------------------
 * Intended to run every few minutes via cron/systemd timer:
 *   * * * * * php /path/to/pdf2word/scripts/cleanup.php
 *
 * Deletes uploads/converted files (and their metadata) once they
 * pass the retention window, independent of the opportunistic
 * cleanup that also runs probabilistically on normal API requests.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

require_once __DIR__ . '/../includes/bootstrap.php';

JobManager::cleanupExpired();

echo "Cleanup complete: " . date('c') . PHP_EOL;
