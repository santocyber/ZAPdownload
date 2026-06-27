<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_admin();

$message = '';
$error = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        verify_csrf_token($_POST['csrf_token'] ?? null);
        $action = (string) ($_POST['action'] ?? '');

        if ($action === 'create') {
            auth_create_user(
                (string) ($_POST['username'] ?? ''),
                (string) ($_POST['password'] ?? ''),
                (string) ($_POST['role'] ?? 'user'),
                isset($_POST['active']) ? 1 : 0
            );
            $message = 'Usuario criado.';
        }

        if ($action === 'update') {
            $userId = (int) ($_POST['user_id'] ?? 0);
            $role = (string) ($_POST['role'] ?? 'user');
            $active = isset($_POST['active']) ? 1 : 0;
            $password = trim((string) ($_POST['password'] ?? ''));

            if ($userId === current_user_id() && ($role !== 'admin' || $active !== 1)) {
                throw new RuntimeException('Voce nao pode remover seu proprio acesso admin.');
            }

            auth_update_user($userId, $role, $active, $password !== '' ? $password : null);
            $message = 'Usuario atualizado.';
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

$users = auth_list_users();
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Admin - Usuarios</title>
    <link rel="stylesheet" href="style.css">
</head>
<body class="admin-page">
    <main class="admin-shell">
        <header class="admin-header">
            <div>
                <p class="eyebrow">Administracao</p>
                <h1>Usuarios</h1>
            </div>
            <nav class="admin-nav">
                <a class="button secondary" href="index.php">Voltar</a>
                <a class="button ghost" href="logout.php">Sair</a>
            </nav>
        </header>

        <?php if ($message !== ''): ?>
            <div class="auth-success"><?= htmlspecialchars($message, ENT_QUOTES, 'UTF-8') ?></div>
        <?php endif; ?>

        <?php if ($error !== ''): ?>
            <div class="auth-error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
        <?php endif; ?>

        <section class="admin-card">
            <h2>Criar usuario</h2>
            <form method="post" class="admin-form">
                <input type="hidden" name="csrf_token" value="<?= htmlspecialchars(csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
                <input type="hidden" name="action" value="create">
                <label>
                    <span>Usuario</span>
                    <input name="username" type="text" required placeholder="usuario">
                </label>
                <label>
                    <span>Senha</span>
                    <input name="password" type="password" required placeholder="minimo 6 caracteres">
                </label>
                <label>
                    <span>Tipo</span>
                    <select name="role">
                        <option value="user">Usuario</option>
                        <option value="admin">Admin</option>
                    </select>
                </label>
                <label class="check-label">
                    <input name="active" type="checkbox" checked>
                    <span>Ativo</span>
                </label>
                <button class="button" type="submit">Cadastrar</button>
            </form>
        </section>

        <section class="admin-card">
            <h2>Usuarios cadastrados</h2>
            <div class="user-list">
                <?php foreach ($users as $user): ?>
                    <form method="post" class="user-row">
                        <input type="hidden" name="csrf_token" value="<?= htmlspecialchars(csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
                        <input type="hidden" name="action" value="update">
                        <input type="hidden" name="user_id" value="<?= (int) $user['id'] ?>">
                        <div class="user-info">
                            <strong><?= htmlspecialchars((string) $user['username'], ENT_QUOTES, 'UTF-8') ?></strong>
                            <small><?= (int) $user['conversation_count'] ?> conversas importadas</small>
                        </div>
                        <select name="role">
                            <option value="user" <?= $user['role'] === 'user' ? 'selected' : '' ?>>Usuario</option>
                            <option value="admin" <?= $user['role'] === 'admin' ? 'selected' : '' ?>>Admin</option>
                        </select>
                        <label class="check-label compact">
                            <input name="active" type="checkbox" <?= (int) $user['active'] === 1 ? 'checked' : '' ?>>
                            <span>Ativo</span>
                        </label>
                        <input name="password" type="password" placeholder="nova senha opcional">
                        <button class="button small" type="submit">Salvar</button>
                    </form>
                <?php endforeach; ?>
            </div>
        </section>
    </main>
</body>
</html>
