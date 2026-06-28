<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_login();

$action = $_GET['action'] ?? 'conversations';

try {
    match ($action) {
        'conversations' => conversations(),
        'messages' => messages(),
        'search' => search_messages(),
        'delete_conversation' => delete_conversation(),
        default => fail_response('Acao invalida.', 404),
    };
} catch (Throwable $exception) {
    fail_response($exception->getMessage(), 500);
}

function conversations(): void
{
    $db = Database::connection();
    $stmt = $db->prepare(<<<'SQL'
SELECT
    c.id,
    c.title,
    c.source_file,
    c.message_count,
    c.imported_at,
    lm.body AS last_message,
    lm.sent_at AS last_date
FROM conversations c
LEFT JOIN messages lm ON lm.id = (
    SELECT id
    FROM messages
    WHERE conversation_id = c.id
    ORDER BY COALESCE(sent_at, '') DESC, id DESC
    LIMIT 1
)
WHERE c.user_id = :user_id
ORDER BY c.imported_at DESC, c.id DESC
SQL);
    $stmt->execute([':user_id' => current_user_id()]);

    json_response([
        'success' => true,
        'conversations' => $stmt->fetchAll(),
    ]);
}

function messages(): void
{
    $conversationId = max(0, (int) ($_GET['conversation_id'] ?? 0));
    $limit = min(2000, max(1, (int) ($_GET['limit'] ?? 500)));
    $offset = max(0, (int) ($_GET['offset'] ?? 0));

    if ($conversationId < 1) {
        fail_response('Conversa invalida.', 400);
    }

    $db = Database::connection();
    $stmt = $db->prepare(<<<'SQL'
SELECT m.id, m.conversation_id, m.sender, m.body, m.sent_at, m.media_path, m.raw_line
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.conversation_id = :conversation_id AND c.user_id = :user_id
ORDER BY m.sent_at DESC, m.id DESC
LIMIT :limit OFFSET :offset
SQL);
    $stmt->bindValue(':conversation_id', $conversationId, PDO::PARAM_INT);
    $stmt->bindValue(':user_id', current_user_id(), PDO::PARAM_INT);
    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
    $stmt->execute();

    json_response([
        'success' => true,
        'messages' => array_map('format_message', $stmt->fetchAll()),
    ]);
}

function search_messages(): void
{
    $query = trim((string) ($_GET['q'] ?? ''));
    $conversationId = max(0, (int) ($_GET['conversation_id'] ?? 0));
    $limit = min(200, max(1, (int) ($_GET['limit'] ?? 80)));
    $terms = search_terms($query);
    $dateStart = parse_date_filter((string) ($_GET['date_start'] ?? ''), false);
    $dateEnd = parse_date_filter((string) ($_GET['date_end'] ?? ''), true);
    $hasDateFilter = $dateStart !== null || $dateEnd !== null;
    $sortDirection = strtolower((string) ($_GET['sort'] ?? 'desc')) === 'asc' ? 'ASC' : 'DESC';

    if (strlen($query) < 2 && !$hasDateFilter) {
        json_response([
            'success' => true,
            'messages' => [],
        ]);
    }

    json_response([
        'success' => true,
        'messages' => array_map('format_message', search_with_like($query, $terms, $conversationId, $limit, $dateStart, $dateEnd, $sortDirection)),
    ]);
}

function search_with_like(string $query, array $terms, int $conversationId, int $limit, ?string $dateStart, ?string $dateEnd, string $sortDirection): array
{
    $db = Database::connection();
    $where = ['c.user_id = :user_id'];
    $searchClauses = [];
    $normalizedQuery = normalize_search_text($query);
    $termClauses = [];

    if ($conversationId > 0) {
        $where[] = 'm.conversation_id = :conversation_id';
    }

    if ($dateStart !== null) {
        $where[] = 'm.sent_at >= :date_start';
    }

    if ($dateEnd !== null) {
        $where[] = 'm.sent_at <= :date_end';
    }

    if ($normalizedQuery !== '') {
        $searchClauses[] = "COALESCE(m.body_search, '') LIKE :phrase ESCAPE '\\'";
        $searchClauses[] = "COALESCE(m.sender_search, '') LIKE :phrase ESCAPE '\\'";
    }

    if ($query !== '') {
        $searchClauses[] = "m.body LIKE :raw_phrase ESCAPE '\\'";
        $searchClauses[] = "COALESCE(m.sender, '') LIKE :raw_phrase ESCAPE '\\'";
    }

    foreach ($terms as $index => $term) {
        $termClauses[] = "(COALESCE(m.body_search, '') LIKE :term{$index} ESCAPE '\\' OR COALESCE(m.sender_search, '') LIKE :term{$index} ESCAPE '\\')";
    }

    if ($termClauses !== []) {
        $searchClauses[] = '(' . implode(' AND ', $termClauses) . ')';
    }

    if ($searchClauses !== []) {
        $where[] = '(' . implode(' OR ', $searchClauses) . ')';
    }

    $whereSql = $where !== [] ? 'WHERE ' . implode(' AND ', $where) : '';
    $orderSql = $sortDirection === 'ASC'
        ? "ORDER BY COALESCE(m.sent_at, '') ASC, m.id ASC"
        : "ORDER BY COALESCE(m.sent_at, '') DESC, m.id DESC";

    $stmt = $db->prepare(<<<SQL
SELECT
    m.id,
    m.conversation_id,
    m.sender,
    m.body,
    m.sent_at,
    m.media_path,
    m.raw_line,
    c.title AS conversation_title,
    m.body AS snippet
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
{$whereSql}
{$orderSql}
LIMIT :limit
SQL);

    if ($normalizedQuery !== '') {
        $stmt->bindValue(':phrase', like_pattern($normalizedQuery));
    }

    if ($query !== '') {
        $stmt->bindValue(':raw_phrase', like_pattern($query));
    }

    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':user_id', current_user_id(), PDO::PARAM_INT);

    foreach ($terms as $index => $term) {
        $stmt->bindValue(':term' . $index, like_pattern($term));
    }

    if ($conversationId > 0) {
        $stmt->bindValue(':conversation_id', $conversationId, PDO::PARAM_INT);
    }

    if ($dateStart !== null) {
        $stmt->bindValue(':date_start', $dateStart);
    }

    if ($dateEnd !== null) {
        $stmt->bindValue(':date_end', $dateEnd);
    }

    $stmt->execute();

    return $stmt->fetchAll();
}

function like_pattern(string $value): string
{
    return '%' . str_replace(['\\', '%', '_'], ['\\\\', '\\%', '\\_'], $value) . '%';
}

function parse_date_filter(string $value, bool $endOfDay): ?string
{
    $value = trim($value);

    if ($value === '' || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $value)) {
        return null;
    }

    [$year, $month, $day] = array_map('intval', explode('-', $value));

    if (!checkdate($month, $day, $year)) {
        return null;
    }

    return sprintf('%04d-%02d-%02d %s', $year, $month, $day, $endOfDay ? '23:59:59' : '00:00:00');
}

function delete_conversation(): void
{
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        fail_response('Metodo nao permitido.', 405);
    }

    $payload = request_json();
    $conversationId = max(0, (int) ($payload['conversation_id'] ?? $_POST['conversation_id'] ?? 0));

    if ($conversationId < 1) {
        fail_response('Conversa invalida.', 400);
    }

    $db = Database::connection();
    $conversationStmt = $db->prepare('SELECT id, source_file FROM conversations WHERE id = :id AND user_id = :user_id');
    $conversationStmt->execute([
        ':id' => $conversationId,
        ':user_id' => current_user_id(),
    ]);
    $conversation = $conversationStmt->fetch();

    if (!$conversation) {
        fail_response('Conversa nao encontrada.', 404);
    }

    $mediaStmt = $db->prepare(<<<'SQL'
SELECT DISTINCT media_path
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.conversation_id = :id AND c.user_id = :user_id AND m.media_path IS NOT NULL AND m.media_path != ''
SQL);
    $mediaStmt->execute([
        ':id' => $conversationId,
        ':user_id' => current_user_id(),
    ]);
    $mediaPaths = array_column($mediaStmt->fetchAll(), 'media_path');

    $db->beginTransaction();

    try {
        $deleteStmt = $db->prepare('DELETE FROM conversations WHERE id = :id AND user_id = :user_id');
        $deleteStmt->execute([
            ':id' => $conversationId,
            ':user_id' => current_user_id(),
        ]);
        $db->commit();
    } catch (Throwable $exception) {
        $db->rollBack();
        throw $exception;
    }

    delete_inside_storage(UPLOAD_DIR, (string) $conversation['source_file']);

    foreach ($mediaPaths as $mediaPath) {
        delete_inside_storage(MEDIA_DIR, (string) $mediaPath);
    }

    json_response([
        'success' => true,
        'deleted_id' => $conversationId,
    ]);
}

function delete_inside_storage(string $root, string $relativePath): void
{
    $relativePath = str_replace('\\', '/', $relativePath);

    if ($relativePath === '' || str_starts_with($relativePath, '/') || str_contains($relativePath, '..') || str_contains($relativePath, "\0")) {
        return;
    }

    $rootReal = realpath($root);
    $path = realpath($root . '/' . $relativePath);

    if ($rootReal === false || $path === false || !str_starts_with($path, $rootReal) || !is_file($path)) {
        return;
    }

    unlink($path);

    $directory = dirname($path);

    while ($directory !== $rootReal && is_dir($directory)) {
        $entries = scandir($directory);

        if ($entries === false || count($entries) > 2) {
            break;
        }

        rmdir($directory);
        $directory = dirname($directory);
    }
}

function format_message(array $message): array
{
    $message['media_url'] = $message['media_path']
        ? 'media.php?file=' . rawurlencode((string) $message['media_path'])
        : null;

    return $message;
}
