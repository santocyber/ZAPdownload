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

$size = filesize($path);
$ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));

$mimeMap = [
    'mp3'  => 'audio/mpeg',
    'm4a'  => 'audio/mp4',
    'opus' => 'audio/ogg',
    'ogg'  => 'audio/ogg',
    'wav'  => 'audio/wav',
    'aac'  => 'audio/aac',
    'mp4'  => 'video/mp4',
    'mov'  => 'video/quicktime',
    'm4v'  => 'video/mp4',
    '3gp'  => 'video/3gpp',
    'jpg'  => 'image/jpeg',
    'jpeg' => 'image/jpeg',
    'png'  => 'image/png',
    'gif'  => 'image/gif',
    'webp' => 'image/webp',
    'pdf'  => 'application/pdf',
    'doc'  => 'application/msword',
    'docx' => 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];

$mime = $mimeMap[$ext] ?? null;

if ($mime === null) {
    if (class_exists('finfo')) {
        $finfo = new finfo(FILEINFO_MIME_TYPE);
        $detected = $finfo->file($path);
        $mime = (is_string($detected) && $detected !== '') ? $detected : 'application/octet-stream';
    } else {
        $mime = 'application/octet-stream';
    }
}

$isMedia = str_starts_with($mime, 'audio/') || str_starts_with($mime, 'video/');

header('Accept-Ranges: bytes');
header('Content-Type: ' . $mime);
header('Cache-Control: no-cache, must-revalidate');

if (isset($_SERVER['HTTP_RANGE'])) {
    preg_match('/bytes=(\d+)-(\d*)/', $_SERVER['HTTP_RANGE'], $matches);
    $start = (int) $matches[1];
    $end = $matches[2] !== '' ? (int) $matches[2] : $size - 1;

    if ($start >= $size || $start > $end) {
        http_response_code(416);
        header('Content-Range: bytes */' . $size);
        exit;
    }

    http_response_code(206);
    header("Content-Range: bytes $start-$end/$size");
    header('Content-Length: ' . ($end - $start + 1));

    if (!$isMedia) {
        header('Content-Disposition: inline; filename="' . basename($path) . '"');
    }

    $fp = fopen($path, 'rb');
    fseek($fp, $start);
    echo fread($fp, $end - $start + 1);
    fclose($fp);
} else {
    header('Content-Length: ' . $size);

    if (!$isMedia) {
        header('Content-Disposition: inline; filename="' . basename($path) . '"');
    }

    readfile($path);
}
