<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_login();

$file = (string) ($_GET['file'] ?? '');
$file = str_replace('\\', '/', $file);

if ($file === '' || str_contains($file, "\0") || str_starts_with($file, '/') || str_contains($file, '..')) {
    http_response_code(400);
    exit('Arquivo invalido.');
}

$mediaRoot = realpath(MEDIA_DIR);
$path = realpath(MEDIA_DIR . '/' . $file);

if ($mediaRoot === false || $path === false || !str_starts_with($path, $mediaRoot) || !is_file($path)) {
    http_response_code(404);
    exit('Arquivo nao encontrado.');
}

$db = Database::connection();
$stmt = $db->prepare(<<<'SQL'
SELECT 1
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE c.user_id = :user_id AND m.media_path = :media_path
LIMIT 1
SQL);
$stmt->execute([
    ':user_id' => current_user_id(),
    ':media_path' => $file,
]);

if (!$stmt->fetchColumn()) {
    http_response_code(403);
    exit('Acesso negado.');
}

$mime = 'application/octet-stream';

if (class_exists('finfo')) {
    $finfo = new finfo(FILEINFO_MIME_TYPE);
    $detected = $finfo->file($path);

    if (is_string($detected) && $detected !== '') {
        $mime = $detected;
    }
}

header('Content-Type: ' . $mime);
header('Content-Length: ' . filesize($path));
header('Content-Disposition: inline; filename="' . basename($path) . '"');
readfile($path);
