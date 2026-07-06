<?php
/**
 * JobManager.php
 * ---------------------------------------------------------------
 * Owns the full lifecycle of a conversion job:
 *   1. Persist the uploaded PDF under a random, non-guessable name.
 *   2. Launch the Python conversion worker asynchronously.
 *   3. Track/merge progress reported by the worker's status file.
 *   4. Serve the finished DOCX and enforce a retention TTL.
 *
 * All job state lives on disk as small JSON files so the app has no
 * database dependency and stays trivially deployable.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class JobManager
{
    private static function jobMetaPath(string $jobId): string
    {
        return Config::uploadsPath() . '/' . $jobId . '.meta.json';
    }

    private static function jobStatusPath(string $jobId): string
    {
        return Config::uploadsPath() . '/' . $jobId . '.status.json';
    }

    private static function uploadedPdfPath(string $jobId): string
    {
        return Config::uploadsPath() . '/' . $jobId . '.pdf';
    }

    private static function outputDocxPath(string $jobId): string
    {
        return Config::convertedPath() . '/' . $jobId . '.docx';
    }

    /** Validates a job id looks like one we would have generated. */
    public static function isValidJobId(string $jobId): bool
    {
        return (bool) preg_match('/^[a-f0-9]{32}$/', $jobId);
    }

    /**
     * Moves the validated upload into place, writes metadata and
     * kicks off the background conversion process.
     *
     * @return array{jobId: string}
     */
    public static function createJob(array $uploadedFile): array
    {
        $jobId = Security::randomId();
        $originalName = Security::sanitizeDisplayFilename($uploadedFile['name']);
        $pdfPath = self::uploadedPdfPath($jobId);

        if (!is_dir(Config::uploadsPath())) {
            @mkdir(Config::uploadsPath(), 0750, true);
        }
        if (!is_dir(Config::convertedPath())) {
            @mkdir(Config::convertedPath(), 0750, true);
        }

        if (!move_uploaded_file($uploadedFile['tmp_name'], $pdfPath)) {
            throw new RuntimeException('Failed to store the uploaded file.');
        }
        @chmod($pdfPath, 0640);

        $meta = [
            'jobId'         => $jobId,
            'originalName'  => $originalName,
            'createdAt'     => time(),
            'expiresAt'     => time() + (Config::retentionMinutes() * 60),
            'sizeBytes'     => $uploadedFile['size'],
        ];
        file_put_contents(self::jobMetaPath($jobId), json_encode($meta), LOCK_EX);

        // Initial status, before the Python process reports anything.
        file_put_contents(self::jobStatusPath($jobId), json_encode([
            'state'    => 'queued',
            'message'  => 'Uploading your document...',
            'progress' => 5,
        ]), LOCK_EX);

        self::launchWorker($jobId);

        Logger::info('Job created', ['jobId' => $jobId, 'name' => $originalName]);

        return ['jobId' => $jobId];
    }

    /** Spawns the Python worker without blocking the HTTP response. */
    private static function launchWorker(string $jobId): void
    {
        $pdfPath = self::uploadedPdfPath($jobId);
        $docxPath = self::outputDocxPath($jobId);
        $statusPath = self::jobStatusPath($jobId);
        $logPath = Config::logsPath() . '/worker-' . $jobId . '.log';

        $command = [
            Config::pythonBinary(),
            Config::converterScript(),
            $pdfPath,
            $docxPath,
            $statusPath,
        ];

        $descriptors = [
            0 => ['pipe', 'r'],
            1 => ['file', $logPath, 'a'],
            2 => ['file', $logPath, 'a'],
        ];

        // bypass_shell avoids shell interpolation entirely — arguments are
        // passed straight to execve(), eliminating shell injection risk.
        $process = proc_open($command, $descriptors, $pipes, Config::rootPath(), null, [
            'bypass_shell' => true,
        ]);

        if (is_resource($process)) {
            fclose($pipes[0]);
            // Deliberately do NOT call proc_close()/proc_get_status() here:
            // proc_close() blocks until the child exits, which would make
            // every upload request wait for the full conversion. Since
            // stdout/stderr are redirected to log files (not pipes), the
            // worker keeps running independently after this request ends.
        } else {
            Logger::error('Failed to launch conversion worker', ['jobId' => $jobId]);
            file_put_contents($statusPath, json_encode([
                'state'    => 'error',
                'message'  => 'Could not start the conversion process.',
                'progress' => 0,
            ]), LOCK_EX);
        }
    }

    /**
     * Reads current status, applying a stall/timeout guard.
     *
     * @return array<string, mixed>
     */
    public static function getStatus(string $jobId): array
    {
        $metaPath = self::jobMetaPath($jobId);
        $statusPath = self::jobStatusPath($jobId);

        if (!is_file($metaPath) || !is_file($statusPath)) {
            return ['state' => 'not_found', 'message' => 'Job not found or has expired.', 'progress' => 0];
        }

        $meta = json_decode((string) file_get_contents($metaPath), true) ?: [];
        $status = json_decode((string) file_get_contents($statusPath), true) ?: [];

        if (($status['state'] ?? '') === 'processing' || ($status['state'] ?? '') === 'queued') {
            $elapsed = time() - (int) ($meta['createdAt'] ?? time());
            if ($elapsed > Config::jobTimeoutSeconds()) {
                $status = [
                    'state'    => 'error',
                    'message'  => 'Conversion timed out. Please try again.',
                    'progress' => 0,
                ];
                Logger::warning('Job timed out', ['jobId' => $jobId]);
            }
        }

        if (($status['state'] ?? '') === 'done' && !is_file(self::outputDocxPath($jobId))) {
            $status = ['state' => 'error', 'message' => 'The converted file could not be found.', 'progress' => 0];
        }

        $status['originalName'] = $meta['originalName'] ?? 'document.pdf';
        return $status;
    }

    /**
     * @return array{path: string, downloadName: string}|null
     */
    public static function getDownload(string $jobId): ?array
    {
        $metaPath = self::jobMetaPath($jobId);
        $docxPath = self::outputDocxPath($jobId);

        if (!is_file($metaPath) || !is_file($docxPath)) {
            return null;
        }

        $meta = json_decode((string) file_get_contents($metaPath), true) ?: [];
        $baseName = pathinfo($meta['originalName'] ?? 'document.pdf', PATHINFO_FILENAME);
        $downloadName = Security::sanitizeDisplayFilename($baseName) . '.docx';

        return ['path' => $docxPath, 'downloadName' => $downloadName];
    }

    /** Deletes every artifact for a single job (used by cleanup + client-initiated removal). */
    public static function purgeJob(string $jobId): void
    {
        foreach ([
            self::jobMetaPath($jobId),
            self::jobStatusPath($jobId),
            self::uploadedPdfPath($jobId),
            self::outputDocxPath($jobId),
            Config::logsPath() . '/worker-' . $jobId . '.log',
        ] as $path) {
            if (is_file($path)) {
                @unlink($path);
            }
        }
    }

    /** Sweeps uploads/converted directories for expired jobs. Cheap enough to run opportunistically. */
    public static function cleanupExpired(): void
    {
        $now = time();
        $metaFiles = glob(Config::uploadsPath() . '/*.meta.json') ?: [];

        foreach ($metaFiles as $metaFile) {
            $meta = json_decode((string) file_get_contents($metaFile), true);
            if (!is_array($meta)) {
                continue;
            }
            if (($meta['expiresAt'] ?? 0) < $now) {
                self::purgeJob((string) ($meta['jobId'] ?? ''));
            }
        }
    }
}
