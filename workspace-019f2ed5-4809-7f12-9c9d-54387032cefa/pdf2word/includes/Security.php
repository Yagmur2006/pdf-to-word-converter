<?php
/**
 * Security.php
 * ---------------------------------------------------------------
 * CSRF token issuance/validation and small input-sanitizing helpers.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class Security
{
    private const CSRF_SESSION_KEY = 'csrf_token';

    /** Returns the current CSRF token, generating one if needed. */
    public static function csrfToken(): string
    {
        if (empty($_SESSION[self::CSRF_SESSION_KEY])) {
            $_SESSION[self::CSRF_SESSION_KEY] = bin2hex(random_bytes(32));
        }
        return $_SESSION[self::CSRF_SESSION_KEY];
    }

    /** Validates a token supplied by the client using constant-time comparison. */
    public static function verifyCsrfToken(?string $token): bool
    {
        if (!$token || empty($_SESSION[self::CSRF_SESSION_KEY])) {
            return false;
        }
        return hash_equals($_SESSION[self::CSRF_SESSION_KEY], $token);
    }

    /** Generates a cryptographically random, filesystem-safe job identifier. */
    public static function randomId(int $bytes = 16): string
    {
        return bin2hex(random_bytes($bytes));
    }

    /**
     * Strips a filename down to a safe, display-only string.
     * Never used to build filesystem paths (random IDs are used for that).
     */
    public static function sanitizeDisplayFilename(string $filename): string
    {
        $filename = basename($filename);
        $filename = preg_replace('/[^\w\-. ]+/u', '_', $filename) ?? 'document.pdf';
        return mb_substr($filename, 0, 150);
    }

    /** Best-effort client IP resolution for rate limiting/logging only. */
    public static function clientIp(): string
    {
        foreach (['HTTP_X_FORWARDED_FOR', 'HTTP_CLIENT_IP', 'REMOTE_ADDR'] as $key) {
            if (!empty($_SERVER[$key])) {
                $parts = explode(',', $_SERVER[$key]);
                return trim($parts[0]);
            }
        }
        return '0.0.0.0';
    }
}
