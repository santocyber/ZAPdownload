<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/bootstrap.php';

require_login();

$currentUser = current_user();
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>WhatsApp Export Viewer</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="app-shell">
        <aside class="sidebar">
            <header class="brand">
                <div>
                    <p class="eyebrow">Backup local</p>
                    <h1>Conversas</h1>
                </div>
                <div class="user-actions">
                    <span class="current-user"><?= htmlspecialchars((string) ($currentUser['username'] ?? ''), ENT_QUOTES, 'UTF-8') ?></span>
                    <?php if (is_admin()): ?>
                        <a class="mini-link" href="admin-users.php">Admin</a>
                    <?php endif; ?>
                    <a class="mini-link danger-link" href="logout.php">Sair</a>
                    <button id="refreshButton" class="icon-button" type="button" title="Atualizar">R</button>
                </div>
            </header>

            <section id="dropArea" class="upload-card">
                <div class="upload-copy">
                    <strong>Importar exportacao</strong>
                    <span>Arraste um `.txt` ou `.zip` grande aqui.</span>
                </div>
                <div class="upload-actions">
                    <span id="browseButton" class="button secondary" role="button" tabindex="0">Escolher</span>
                    <button id="startUpload" class="button" type="button" disabled>Enviar</button>
                    <button id="pauseUpload" class="button ghost" type="button" disabled>Pausar</button>
                </div>
                <div class="progress-wrap" aria-label="Progresso do upload">
                    <progress id="progressBar" value="0" max="100"></progress>
                    <span id="progressText">Nenhum arquivo selecionado.</span>
                </div>
            </section>

            <label class="search-box">
                <span>Buscar geral</span>
                <input id="globalSearchInput" type="search" placeholder="palavra, pessoa ou trecho">
            </label>
            <div class="date-filter" aria-label="Filtro de data geral">
                <label>
                    <span>De</span>
                    <input id="globalDateStart" type="date">
                </label>
                <label>
                    <span>Ate</span>
                    <input id="globalDateEnd" type="date">
                </label>
                <button id="clearGlobalSearch" class="button ghost small" type="button">Limpar</button>
            </div>

            <nav id="conversationList" class="conversation-list" aria-label="Conversas importadas"></nav>
        </aside>

        <main class="chat-panel">
            <header class="chat-header">
                <div class="chat-title-block">
                    <p id="chatSubtitle" class="eyebrow">Selecione uma conversa</p>
                    <h2 id="chatTitle">WhatsApp Export Viewer</h2>
                </div>
                <div class="chat-tools">
                    <label class="chat-search">
                        <span>Buscar neste chat</span>
                        <input id="chatSearchInput" type="search" placeholder="mensagem neste chat" disabled>
                    </label>
                    <div class="chat-date-filter" aria-label="Filtro de data do chat">
                        <label>
                            <span>De</span>
                            <input id="chatDateStart" type="date" disabled>
                        </label>
                        <label>
                            <span>Ate</span>
                            <input id="chatDateEnd" type="date" disabled>
                        </label>
                    </div>
                    <button id="clearChatSearch" class="button ghost small" type="button" disabled>Limpar</button>
                    <span id="messageCount" class="message-count"></span>
                </div>
            </header>

            <section id="messages" class="messages empty-state">
                <div>
                    <h3>Importe uma exportacao do WhatsApp</h3>
                    <p>Use `.txt` para conversas simples ou `.zip` para incluir midias exportadas.</p>
                </div>
            </section>
        </main>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/resumablejs@1.1.0/resumable.js"></script>
    <script src="app.js"></script>
</body>
</html>
