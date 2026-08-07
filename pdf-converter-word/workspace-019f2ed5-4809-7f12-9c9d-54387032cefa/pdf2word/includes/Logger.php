<?php
/**
 * Logger.php
 * ---------------------------------------------------------------
 * Minimal, dependency-free file logger. Writes one JSON line per
 * event to a daily log file so entries stay greppable and rotate
 * automatically without extra tooling.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class Logger
{
    private static function logFile(): string
    {
        return Config::logsPath() . '/app-' . date('Y-m-d') . '.log';
    }

    private static function write(string $level, string $message, array $context = []): void
    {
        $dir = Config::logsPath();
        if (!is_dir($dir)) {
            @mkdir($dir, 0750, true);
        }

        $entry = [
            'time'    => date('c'),
            'level'   => $level,
            'message' => $message,
            'context' => $context,
        ];

        // Best-effort logging: never let a logging failure break the request.
        @file_put_contents(
            self::logFile(),
            json_encode($entry, JSON_UNESCAPED_SLASHES) . PHP_EOL,
            FILE_APPEND | LOCK_EX
        );
    }

    public static function info(string $message, array $context = []): void
    {
        self::write('INFO', $message, $context);
    }

    public static function warning(string $message, array $context = []): void
    {
        self::write('WARNING', $message, $context);
    }

    public static function error(string $message, array $context = []): void
    {
        self::write('ERROR', $message, $context);
    }
}
