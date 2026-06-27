<?php
declare(strict_types=1);

auth_start_session();

function auth_start_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }

    session_name('zapviewer_session');
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'domain' => '',
        'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

function current_user_id(): ?int
{
    $userId = $_SESSION['user_id'] ?? null;

    return is_numeric($userId) ? (int) $userId : null;
}

function current_user(): ?array
{
    static $cachedUser = null;
    static $cachedUserId = null;

    $userId = current_user_id();

    if ($userId === null) {
        return null;
    }

    if ($cachedUser !== null && $cachedUserId === $userId) {
        return $cachedUser;
    }

    $db = Database::connection();
    $stmt = $db->prepare('SELECT id, username, role, active, created_at, last_login_at FROM users WHERE id = :id AND active = 1');
    $stmt->execute([':id' => $userId]);
    $user = $stmt->fetch();

    if (!$user) {
        logout_user();
        return null;
    }

    $cachedUser = $user;
    $cachedUserId = $userId;

    return $cachedUser;
}

function require_login(): void
{
    if (current_user() !== null) {
        return;
    }

    if (auth_is_endpoint_request()) {
        fail_response('Login necessario.', 401);
    }

    header('Location: login.php');
    exit;
}

function require_admin(): void
{
    require_login();

    if (!is_admin()) {
        http_response_code(403);
        exit('Acesso negado.');
    }
}

function is_admin(): bool
{
    $user = current_user();

    return $user !== null && $user['role'] === 'admin';
}

function auth_has_users(): bool
{
    $db = Database::connection();
    return (int) $db->query('SELECT COUNT(*) FROM users')->fetchColumn() > 0;
}

function auth_create_user(string $username, string $password, string $role = 'user', int $active = 1): int
{
    $username = auth_normalize_username($username);
    $role = $role === 'admin' ? 'admin' : 'user';
    $active = $active ? 1 : 0;

    if ($username === '') {
        throw new RuntimeException('Informe um usuario valido.');
    }

    if (strlen($password) < 6) {
        throw new RuntimeException('A senha precisa ter pelo menos 6 caracteres.');
    }

    $db = Database::connection();
    $hadUsers = auth_has_users();
    $stmt = $db->prepare(<<<'SQL'
INSERT INTO users (username, password_hash, role, active, created_at)
VALUES (:username, :password_hash, :role, :active, :created_at)
SQL);

    try {
        $stmt->execute([
            ':username' => $username,
            ':password_hash' => password_hash($password, PASSWORD_DEFAULT),
            ':role' => $role,
            ':active' => $active,
            ':created_at' => gmdate('Y-m-d H:i:s'),
        ]);
    } catch (PDOException $exception) {
        if ($exception->getCode() === '23000') {
            throw new RuntimeException('Este usuario ja existe.');
        }

        throw $exception;
    }

    $userId = (int) $db->lastInsertId();

    if (!$hadUsers) {
        $db->prepare('UPDATE conversations SET user_id = :user_id WHERE user_id IS NULL')->execute([':user_id' => $userId]);
    }

    return $userId;
}

function auth_update_user(int $userId, string $role, int $active, ?string $password = null): void
{
    if ($userId < 1) {
        throw new RuntimeException('Usuario invalido.');
    }

    $role = $role === 'admin' ? 'admin' : 'user';
    $active = $active ? 1 : 0;
    $db = Database::connection();

    if ($password !== null && $password !== '') {
        if (strlen($password) < 6) {
            throw new RuntimeException('A senha precisa ter pelo menos 6 caracteres.');
        }

        $stmt = $db->prepare('UPDATE users SET role = :role, active = :active, password_hash = :password_hash WHERE id = :id');
        $stmt->execute([
            ':role' => $role,
            ':active' => $active,
            ':password_hash' => password_hash($password, PASSWORD_DEFAULT),
            ':id' => $userId,
        ]);

        return;
    }

    $stmt = $db->prepare('UPDATE users SET role = :role, active = :active WHERE id = :id');
    $stmt->execute([
        ':role' => $role,
        ':active' => $active,
        ':id' => $userId,
    ]);
}

function auth_delete_user(int $userId): void
{
    if ($userId < 1) {
        throw new RuntimeException('Usuario invalido.');
    }

    if ($userId === current_user_id()) {
        throw new RuntimeException('Voce nao pode apagar o proprio usuario logado.');
    }

    $db = Database::connection();
    $stmt = $db->prepare('DELETE FROM users WHERE id = :id');
    $stmt->execute([':id' => $userId]);
}

function csrf_token(): string
{
    if (empty($_SESSION['csrf_token']) || !is_string($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }

    return $_SESSION['csrf_token'];
}

function verify_csrf_token(?string $token): void
{
    if (!is_string($token) || !hash_equals(csrf_token(), $token)) {
        throw new RuntimeException('Sessao expirada. Recarregue a pagina e tente novamente.');
    }
}

function auth_login(string $username, string $password): bool
{
    $username = auth_normalize_username($username);
    $db = Database::connection();
    $stmt = $db->prepare('SELECT id, password_hash, active FROM users WHERE username = :username');
    $stmt->execute([':username' => $username]);
    $user = $stmt->fetch();

    if (!$user || (int) $user['active'] !== 1 || !password_verify($password, (string) $user['password_hash'])) {
        return false;
    }

    session_regenerate_id(true);
    $_SESSION['user_id'] = (int) $user['id'];
    $db->prepare('UPDATE users SET last_login_at = :last_login_at WHERE id = :id')->execute([
        ':last_login_at' => gmdate('Y-m-d H:i:s'),
        ':id' => (int) $user['id'],
    ]);

    return true;
}

function logout_user(): void
{
    $_SESSION = [];

    if (ini_get('session.use_cookies')) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $params['path'], $params['domain'], (bool) $params['secure'], (bool) $params['httponly']);
    }

    if (session_status() === PHP_SESSION_ACTIVE) {
        session_destroy();
    }
}

function auth_normalize_username(string $username): string
{
    $username = strtolower(trim($username));
    $username = preg_replace('/[^a-z0-9._-]/', '', $username) ?? '';

    return substr($username, 0, 60);
}

function auth_list_users(): array
{
    $db = Database::connection();
    $stmt = $db->query(<<<'SQL'
SELECT
    u.id,
    u.username,
    u.role,
    u.active,
    u.created_at,
    u.last_login_at,
    COUNT(c.id) AS conversation_count
FROM users u
LEFT JOIN conversations c ON c.user_id = u.id
GROUP BY u.id
ORDER BY u.created_at ASC, u.id ASC
SQL);

    return $stmt->fetchAll();
}

function auth_is_endpoint_request(): bool
{
    $script = basename((string) ($_SERVER['SCRIPT_NAME'] ?? ''));

    return in_array($script, ['api.php', 'import.php', 'upload-chunk.php', 'media.php'], true);
}
