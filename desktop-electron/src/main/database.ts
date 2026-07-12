import Database from "better-sqlite3";
import { ensureStorage } from "./storage";

let db: Database.Database | null = null;

export function connection(): Database.Database {
  if (!db) {
    const paths = ensureStorage();
    db = new Database(paths.database);
    db.pragma("foreign_keys = ON");
    db.pragma("journal_mode = WAL");
    db.pragma("synchronous = NORMAL");
    migrate(db);
  }
  return db;
}

export function closeDatabase(): void {
  db?.close();
  db = null;
}

function migrate(database: Database.Database): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS chats (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      source_file TEXT,
      message_count INTEGER NOT NULL DEFAULT 0,
      first_message_at TEXT,
      last_message_at TEXT,
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id INTEGER NOT NULL,
      sender TEXT,
      body TEXT NOT NULL,
      sender_search TEXT,
      body_search TEXT,
      sent_at TEXT,
      media_path TEXT,
      raw_line INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS media (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id INTEGER NOT NULL,
      original_name TEXT NOT NULL,
      stored_path TEXT NOT NULL,
      mime_type TEXT,
      size INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS imports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_path TEXT NOT NULL,
      source_type TEXT NOT NULL,
      chat_id INTEGER,
      status TEXT NOT NULL,
      error TEXT,
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id);
    CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
    CREATE INDEX IF NOT EXISTS idx_chats_imported_at ON chats(imported_at);
  `);

  try {
    database.exec(`
      CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
        sender,
        body,
        content='messages',
        content_rowid='id'
      );

      CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, sender, body) VALUES (new.id, new.sender, new.body);
      END;

      CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, sender, body) VALUES('delete', old.id, old.sender, old.body);
      END;

      CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, sender, body) VALUES('delete', old.id, old.sender, old.body);
        INSERT INTO messages_fts(rowid, sender, body) VALUES (new.id, new.sender, new.body);
      END;
    `);
  } catch {
    // Some SQLite builds omit FTS5; search falls back to normalized LIKE queries.
  }
}

export function normalizeSearchText(value: string | null | undefined): string {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

export function ftsAvailable(): boolean {
  const row = connection()
    .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'")
    .get();
  return Boolean(row);
}
