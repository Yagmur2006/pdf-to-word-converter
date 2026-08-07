<?php
/**
 * bootstrap.php
 * ---------------------------------------------------------------
 * Shared entry point for every API script. Sets strict error
 * reporting, safe session flags, a JSON error handler and loads all
 * core classes. Nothing here echoes output — that is the job of the
 * individual endpoints via Response.php.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

// Errors are logged, never printed (avoid leaking paths/stack traces).
ini_set('display_errors', '0');
error_reporting(E_ALL);

date_default_timezone_set('UTC');

require_once __DIR__ . '/Config.php';
require_once __DIR__ . '/Logger.php';
require_once __DIR__ . '/Security.php';
require_once __DIR__ . '/RateLimiter.php';
require_once __DIR__ . '/FileValidator.php';
require_once __DIR__ . '/JobManager.php';
require_once __DIR__ . '/Response.php';

// Harden the session cookie before starting the session (used for CSRF tokens).
if (session_status() === PHP_SESSION_NONE) {
    $secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'domain'   => '',
        'secure'   => $secure,
        'httponly' => true,
        'samesite' => 'Strict',
    ]);
    session_start();
}

// Convert PHP warnings/notices into log entries instead of HTML output.
set_error_handler(static function (int $severity, string $message, string $file, int $line): bool {
    Logger::error('PHP error', [
        'severity' => $severity,
        'message'  => $message,
        'file'     => $file,
        'line'     => $line,
    ]);
    return true; // suppress default handler
});

set_exception_handler(static function (Throwable $e): void {
    Logger::error('Uncaught exception', [
        'message' => $e->getMessage(),
        'file'    => $e->getFile(),
        'line'    => $e->getLine(),
    ]);
    Response::error('Something went wrong. Please try again.', 500);
});

// Lazy, low-cost cleanup: on ~5% of requests, sweep expired files so the
// system stays tidy even without a configured cron job.
if (random_int(1, 100) <= 5) {
    JobManager::cleanupExpired();
}
