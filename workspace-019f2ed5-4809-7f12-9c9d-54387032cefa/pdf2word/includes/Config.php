<?php
/**
 * Config.php
 * ---------------------------------------------------------------
 * Central, immutable application configuration.
 *
 * Every path, limit and security setting used across the backend is
 * defined here so there is a single source of truth. Nothing outside
 * this class should hard-code a path or a limit.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class Config
{
    /** Absolute path to the project root (one level above /includes). */
    public static function rootPath(): string
    {
        return dirname(__DIR__);
    }

    public static function uploadsPath(): string
    {
        return self::rootPath() . '/uploads';
    }

    public static function convertedPath(): string
    {
        return self::rootPath() . '/converted';
    }

    public static function logsPath(): string
    {
        return self::rootPath() . '/logs';
    }

    public static function scriptsPath(): string
    {
        return self::rootPath() . '/scripts';
    }

    /** Path to the python interpreter used for conversion. */
    public static function pythonBinary(): string
    {
        $env = getenv('PDF2WORD_PYTHON_BIN');
        if (is_string($env) && $env !== '') {
            return $env;
        }

        return stripos(PHP_OS_FAMILY, 'Windows') === 0 ? 'python' : 'python3';
    }

    public static function converterScript(): string
    {
        return self::scriptsPath() . '/convert.py';
    }

    /** Maximum accepted upload size, in bytes (100 MB). */
    public static function maxUploadBytes(): int
    {
        return 100 * 1024 * 1024;
    }

    /** File extensions accepted by the uploader. */
    public static function allowedExtensions(): array
    {
        return ['pdf'];
    }

    /** MIME types accepted by the uploader (validated via fileinfo, not client headers). */
    public static function allowedMimeTypes(): array
    {
        return ['application/pdf'];
    }

    /** How long an uploaded/converted file is retained before cleanup, in minutes. */
    public static function retentionMinutes(): int
    {
        return 30;
    }

    /** Simple fixed-window rate limit: max requests per window per IP. */
    public static function rateLimitMaxRequests(): int
    {
        return 20;
    }

    public static function rateLimitWindowSeconds(): int
    {
        return 600; // 10 minutes
    }

    /** Conversion job timeout, in seconds, before it is considered stalled. */
    public static function jobTimeoutSeconds(): int
    {
        return 300;
    }
}
