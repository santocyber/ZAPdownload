<?php
declare(strict_types=1);

final class Database
{
    private static ?PDO $connection = null;
    private static ?bool $ftsAvailable = null;

    public static function connection(): PDO
    {
        if (self::$connection === null) {
            self::$connection = new PDO('sqlite:' . DB_PATH);
            self::$connection->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
            self::$connection->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
            self::$connection->exec('PRAGMA foreign_keys = ON');
            self::$connection->exec('PRAGMA journal_mode = WAL');
            self::$connection->exec('PRAGMA synchronous = NORMAL');
        }

        return self::$connection;
    }

    public static function migrate(): void
    {
        $db = self::connection();

        $db->exec(<<<'SQL'
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);
SQL);

        $db->exec(<<<'SQL'
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    source_file TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
SQL);

        $db->exec(<<<'SQL'
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    sender TEXT,
    body TEXT NOT NULL,
    sender_search TEXT,
    body_search TEXT,
    sent_at TEXT,
    media_path TEXT,
    raw_line INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
SQL);

        $db->exec('CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id)');
        $db->exec('CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at)');

        self::ensureConversationColumns($db);
        $db->exec('CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, imported_at)');
        self::ensureSearchColumns($db);
        self::backfillSearchColumns($db);
        self::createFtsTables($db);
    }

    public static function ftsAvailable(): bool
    {
        if (self::$ftsAvailable !== null) {
            return self::$ftsAvailable;
        }

        $db = self::connection();
        $stmt = $db->query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'");

        self::$ftsAvailable = (bool) $stmt->fetchColumn();

        return self::$ftsAvailable;
    }

    private static function createFtsTables(PDO $db): void
    {
        try {
            $db->exec(<<<'SQL'
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    sender,
    body,
    content='messages',
    content_rowid='id'
);
SQL);

            $db->exec(<<<'SQL'
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, sender, body) VALUES (new.id, new.sender, new.body);
END;
SQL);

            $db->exec(<<<'SQL'
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, sender, body) VALUES('delete', old.id, old.sender, old.body);
END;
SQL);

            $db->exec(<<<'SQL'
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, sender, body) VALUES('delete', old.id, old.sender, old.body);
    INSERT INTO messages_fts(rowid, sender, body) VALUES (new.id, new.sender, new.body);
END;
SQL);

            self::$ftsAvailable = true;
        } catch (Throwable) {
            self::$ftsAvailable = false;
        }
    }

    private static function ensureSearchColumns(PDO $db): void
    {
        $columns = self::tableColumns($db, 'messages');

        if (!in_array('sender_search', $columns, true)) {
            $db->exec('ALTER TABLE messages ADD COLUMN sender_search TEXT');
        }

        if (!in_array('body_search', $columns, true)) {
            $db->exec('ALTER TABLE messages ADD COLUMN body_search TEXT');
        }
    }

    private static function ensureConversationColumns(PDO $db): void
    {
        $columns = self::tableColumns($db, 'conversations');

        if (!in_array('user_id', $columns, true)) {
            $db->exec('ALTER TABLE conversations ADD COLUMN user_id INTEGER');
        }
    }

    private static function tableColumns(PDO $db, string $table): array
    {
        $stmt = $db->query('PRAGMA table_info(' . $table . ')');
        $columns = [];

        foreach ($stmt->fetchAll() as $column) {
            $columns[] = (string) $column['name'];
        }

        return $columns;
    }

    private static function backfillSearchColumns(PDO $db): void
    {
        $select = $db->prepare(<<<'SQL'
SELECT id, sender, body
FROM messages
WHERE body_search IS NULL OR sender_search IS NULL
LIMIT 5000
SQL);
        $update = $db->prepare(<<<'SQL'
UPDATE messages
SET sender_search = :sender_search, body_search = :body_search
WHERE id = :id
SQL);

        while (true) {
            $select->execute();
            $rows = $select->fetchAll();

            if ($rows === []) {
                return;
            }

            $db->beginTransaction();

            try {
                foreach ($rows as $row) {
                    $update->execute([
                        ':sender_search' => normalize_search_text($row['sender'] ?? ''),
                        ':body_search' => normalize_search_text($row['body'] ?? ''),
                        ':id' => (int) $row['id'],
                    ]);
                }

                $db->commit();
            } catch (Throwable $exception) {
                $db->rollBack();
                throw $exception;
            }
        }
    }
}
