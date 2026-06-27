<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_login();

$identifier = clean_identifier(text_param('resumableIdentifier'));
$filename = clean_filename(text_param('resumableFilename'));
$chunkNumber = int_param('resumableChunkNumber');
$totalChunks = int_param('resumableTotalChunks');
$totalSize = int_param('resumableTotalSize');

if ($identifier === '' || $filename === '' || $chunkNumber < 1 || $totalChunks < 1 || $chunkNumber > $totalChunks) {
    fail_response('Parametros de upload invalidos.', 400);
}

if ($totalChunks > 100000 || $totalSize < 1 || $totalSize > MAX_UPLOAD_BYTES) {
    fail_response('Arquivo muito grande ou numero de chunks invalido.', 413);
}

if (!allowed_upload_extension($filename)) {
    fail_response('Formato invalido. Envie .txt ou .zip.', 415);
}

$userUploadPrefix = 'u' . current_user_id() . '_';
$chunkDir = CHUNK_DIR . '/' . $userUploadPrefix . $identifier;
$chunkPath = $chunkDir . '/chunk_' . $chunkNumber;
$finalFilename = $userUploadPrefix . $identifier . '_' . $filename;
$finalPath = UPLOAD_DIR . '/' . $finalFilename;

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    if (is_file($chunkPath) || is_file($finalPath)) {
        http_response_code(200);
        exit;
    }

    http_response_code(204);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    fail_response('Metodo nao permitido.', 405);
}

if (is_file($finalPath)) {
    json_response([
        'success' => true,
        'complete' => true,
        'file' => $finalFilename,
    ]);
}

if (!isset($_FILES['file']) || !is_uploaded_file($_FILES['file']['tmp_name'])) {
    fail_response('Chunk nao recebido.', 400);
}

if (!is_dir($chunkDir)) {
    mkdir($chunkDir, 0775, true);
}

if (!move_uploaded_file($_FILES['file']['tmp_name'], $chunkPath)) {
    fail_response('Nao foi possivel salvar o chunk.', 500);
}

for ($i = 1; $i <= $totalChunks; $i++) {
    if (!is_file($chunkDir . '/chunk_' . $i)) {
        json_response([
            'success' => true,
            'complete' => false,
            'chunk' => $chunkNumber,
        ]);
    }
}

$lockPath = $chunkDir . '/assemble.lock';
$lock = fopen($lockPath, 'c');

if ($lock === false) {
    fail_response('Nao foi possivel criar lock de montagem.', 500);
}

flock($lock, LOCK_EX);

try {
    if (!is_file($finalPath)) {
        $temporaryFinalPath = $finalPath . '.part';
        $output = fopen($temporaryFinalPath, 'wb');

        if ($output === false) {
            throw new RuntimeException('Nao foi possivel criar o arquivo final.');
        }

        for ($i = 1; $i <= $totalChunks; $i++) {
            $input = fopen($chunkDir . '/chunk_' . $i, 'rb');

            if ($input === false) {
                fclose($output);
                throw new RuntimeException('Chunk ausente durante a montagem.');
            }

            stream_copy_to_stream($input, $output);
            fclose($input);
        }

        fclose($output);
        rename($temporaryFinalPath, $finalPath);
    }

    for ($i = 1; $i <= $totalChunks; $i++) {
        $path = $chunkDir . '/chunk_' . $i;

        if (is_file($path)) {
            unlink($path);
        }
    }
} catch (Throwable $exception) {
    flock($lock, LOCK_UN);
    fclose($lock);
    fail_response($exception->getMessage(), 500);
}

flock($lock, LOCK_UN);
fclose($lock);

json_response([
    'success' => true,
    'complete' => true,
    'file' => $finalFilename,
]);
