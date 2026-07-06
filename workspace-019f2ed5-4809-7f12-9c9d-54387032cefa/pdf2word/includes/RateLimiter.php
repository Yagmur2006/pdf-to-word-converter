<?php
/**
 * RateLimiter.php
 * ---------------------------------------------------------------
 * Simple file-based fixed-window rate limiter, keyed by client IP.
 * No external services (Redis/Memcached) required, which keeps the
 * app deployable on plain shared hosting.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class RateLimiter
{
    private static function storageDir(): string
    {
        $dir = Config::logsPath() . '/ratelimit';
        if (!is_dir($dir)) {
            @mkdir($dir, 0750, true);
        }
        return $dir;
    }

    /** Returns true and records a hit if the request is within the allowed rate. */
    public static function allow(string $identifier): bool
    {
        $safeKey = hash('sha256', $identifier);
        $file = self::storageDir() . '/' . $safeKey . '.json';

        $handle = fopen($file, 'c+');
        if ($handle === false) {
            // Fail open rather than blocking legitimate users if disk is unavailable.
            return true;
        }

        flock($handle, LOCK_EX);
        $raw = stream_get_contents($handle);
        $data = $raw ? json_decode($raw, true) : null;

        $now = time();
        $windowSeconds = Config::rateLimitWindowSeconds();
        $maxRequests = Config::rateLimitMaxRequests();

        if (!is_array($data) || ($now - ($data['window_start'] ?? 0)) >= $windowSeconds) {
            $data = ['window_start' => $now, 'count' => 0];
        }

        $data['count']++;
        $allowed = $data['count'] <= $maxRequests;

        ftruncate($handle, 0);
        rewind($handle);
        fwrite($handle, json_encode($data));
        fflush($handle);
        flock($handle, LOCK_UN);
        fclose($handle);

        return $allowed;
    }
}
