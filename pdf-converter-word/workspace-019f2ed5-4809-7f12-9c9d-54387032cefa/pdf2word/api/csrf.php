<?php
/**
 * GET /api/csrf.php
 * Issues a CSRF token for the current session. Called once on page
 * load before the user is allowed to submit an upload.
 */

declare(strict_types=1);

require_once __DIR__ . '/../includes/bootstrap.php';

Response::success(['csrfToken' => Security::csrfToken()]);
