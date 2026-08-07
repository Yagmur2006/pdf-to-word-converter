<?php
/**
 * FileValidator.php
 * ---------------------------------------------------------------
 * Validates uploaded files against extension, MIME (via fileinfo,
 * inspecting real file bytes) and size rules. Returns a structured
 * result rather than throwing, so callers can produce clean user
 * facing messages.
 * ---------------------------------------------------------------
 */

declare(strict_types=1);

final class FileValidator
{
    /**
     * @return array{valid: bool, error?: string}
     */
    public static function validateUpload(array $file): array
    {
        if (!isset($file['error']) || $file['error'] === UPLOAD_ERR_NO_FILE) {
            return ['valid' => false, 'error' => 'No file was uploaded.'];
        }

        if ($file['error'] === UPLOAD_ERR_INI_SIZE || $file['error'] === UPLOAD_ERR_FORM_SIZE) {
            return ['valid' => false, 'error' => 'The file exceeds the 100MB size limit.'];
        }

        if ($file['error'] !== UPLOAD_ERR_OK) {
            return ['valid' => false, 'error' => 'The file failed to upload. Please try again.'];
        }

        if (!is_uploaded_file($file['tmp_name'])) {
            return ['valid' => false, 'error' => 'Invalid upload request.'];
        }

        if ($file['size'] <= 0) {
            return ['valid' => false, 'error' => 'The uploaded file is empty.'];
        }

        if ($file['size'] > Config::maxUploadBytes()) {
            return ['valid' => false, 'error' => 'The file exceeds the 100MB size limit.'];
        }

        $extension = strtolower(pathinfo($file['name'], PATHINFO_EXTENSION));
        if (!in_array($extension, Config::allowedExtensions(), true)) {
            return ['valid' => false, 'error' => 'Only PDF files are supported.'];
        }

        // Inspect the real file content, never trust the client-sent MIME type.
        // Some PHP builds (especially minimal Windows installs) may not have
        // the fileinfo extension enabled. In that case we fall back to
        // a lightweight header check below.
        $detectedMime = false;
        if (function_exists('finfo_open')) {
            $finfo = finfo_open(FILEINFO_MIME_TYPE);
            $detectedMime = $finfo ? finfo_file($finfo, $file['tmp_name']) : false;
            if ($finfo) {
                finfo_close($finfo);
            }
        }

        if ($detectedMime !== false && !in_array($detectedMime, Config::allowedMimeTypes(), true)) {
            return ['valid' => false, 'error' => 'The file does not appear to be a valid PDF.'];
        }

        // Cheap magic-byte check as a second layer of defense.
        $handle = fopen($file['tmp_name'], 'rb');
        $header = $handle ? fread($handle, 5) : '';
        if ($handle) {
            fclose($handle);
        }
        if ($header !== '%PDF-') {
            return ['valid' => false, 'error' => 'The file does not appear to be a valid PDF.'];
        }

        return ['valid' => true];
    }
}
