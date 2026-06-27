<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

if (current_user() !== null) {
    header('Location: index.php');
    exit;
}

$hasUsers = auth_has_users();
$error = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        verify_csrf_token($_POST['csrf_token'] ?? null);
        $action = (string) ($_POST['action'] ?? 'login');
        $username = (string) ($_POST['username'] ?? '');
        $password = (string) ($_POST['password'] ?? '');

        if ($action === 'setup' && !$hasUsers) {
            $confirm = (string) ($_POST['password_confirm'] ?? '');

            if ($password !== $confirm) {
                throw new RuntimeException('As senhas nao conferem.');
            }

            auth_create_user($username, $password, 'admin', 1);

            if (!auth_login($username, $password)) {
                throw new RuntimeException('Admin criado, mas o login automatico falhou.');
            }

            header('Location: index.php');
            exit;
        }

        if ($action === 'login' && auth_login($username, $password)) {
            header('Location: index.php');
            exit;
        }

        $error = 'Usuario ou senha invalidos.';
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - WhatsApp Export Viewer</title>
    <link rel="stylesheet" href="style.css">
</head>
<body class="auth-page">
    <main class="auth-card">
        <p class="eyebrow">Backup local</p>
        <h1><?= $hasUsers ? 'Entrar' : 'Criar primeiro admin' ?></h1>
        <p class="auth-copy">
            <?= $hasUsers ? 'Acesse suas conversas importadas.' : 'Nenhum usuario existe ainda. Crie o administrador inicial.' ?>
        </p>

        <?php if ($error !== ''): ?>
            <div class="auth-error"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
        <?php endif; ?>

        <form method="post" class="auth-form" autocomplete="on">
            <input type="hidden" name="csrf_token" value="<?= htmlspecialchars(csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
            <input type="hidden" name="action" value="<?= $hasUsers ? 'login' : 'setup' ?>">

            <label>
                <span>Usuario</span>
                <input name="username" type="text" required autofocus autocomplete="username" placeholder="admin">
            </label>

            <label>
                <span>Senha</span>
                <input name="password" type="password" required autocomplete="<?= $hasUsers ? 'current-password' : 'new-password' ?>" placeholder="minimo 6 caracteres">
            </label>

            <?php if (!$hasUsers): ?>
                <label>
                    <span>Confirmar senha</span>
                    <input name="password_confirm" type="password" required autocomplete="new-password">
                </label>
            <?php endif; ?>

            <button class="button" type="submit"><?= $hasUsers ? 'Entrar' : 'Criar admin' ?></button>
        </form>
    </main>
</body>
</html>
