<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_login();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    fail_response('Metodo nao permitido.', 405);
}

$payload = request_json();
$file = clean_filename((string) ($payload['file'] ?? $_POST['file'] ?? ''));

if ($file === '') {
    fail_response('Arquivo nao informado.', 400);
}

try {
    $importer = new WhatsAppImporter();
    $result = $importer->import($file);

    json_response([
        'success' => true,
        'conversation' => $result,
    ]);
} catch (Throwable $exception) {
    fail_response($exception->getMessage(), 500);
}
