import { dialog, ipcMain, shell } from "electron";
import { existsSync, statSync } from "node:fs";
import { connection, ftsAvailable, normalizeSearchText } from "./database";
import { importFile } from "./importer";
import { ensureStorage } from "./storage";

export function registerIpc(): void {
  ipcMain.handle("app:info", () => ({ version: process.env.npm_package_version ?? "1.0.0" }));
  ipcMain.handle("settings:get-theme", getTheme);
  ipcMain.handle("settings:set-theme", (_event, theme: string) => setTheme(theme));
  ipcMain.handle("storage:info", getStorageInfo);
  ipcMain.handle("storage:open", () => shell.openPath(ensureStorage().root));

  ipcMain.handle("import:select-file", selectImportFile);
  ipcMain.handle("import:file", (_event, filePath: string) => importFile(filePath));

  ipcMain.handle("chats:list", listChats);
  ipcMain.handle("chats:rename", (_event, chatId: number, title: string) => renameChat(chatId, title));
  ipcMain.handle("chats:delete", (_event, chatId: number) => deleteChat(chatId));
  ipcMain.handle("messages:list", (_event, chatId: number, options = {}) => listMessages(chatId, options as MessageOptions));
  ipcMain.handle("messages:search", (_event, query: string, options = {}) => searchMessages(query, options as SearchOptions));
  ipcMain.handle("media:open", (_event, mediaPath: string) => openMedia(mediaPath));
}

type MessageOptions = { limit?: number; offset?: number };
type SearchOptions = { chatId?: number; limit?: number; offset?: number };

function getTheme(): string {
  const row = connection().prepare("SELECT value FROM settings WHERE key = 'theme'").get() as { value?: string } | undefined;
  return row?.value ?? "system";
}

function setTheme(theme: string): string {
  const allowed = new Set(["light", "dark", "system"]);
  const next = allowed.has(theme) ? theme : "system";
  connection().prepare("INSERT INTO settings (key, value) VALUES ('theme', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value").run(next);
  return next;
}

function getStorageInfo() {
  const paths = ensureStorage();
  const databaseSize = existsSync(paths.database) ? statSync(paths.database).size : 0;
  return { ...paths, databaseSize };
}

async function selectImportFile(): Promise<string | null> {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "WhatsApp Export", extensions: ["txt", "zip"] }],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
}

function listChats() {
  return connection()
    .prepare("SELECT id, title, source_file AS sourceFile, message_count AS messageCount, first_message_at AS firstMessageAt, last_message_at AS lastMessageAt, imported_at AS importedAt FROM chats ORDER BY imported_at DESC, id DESC")
    .all();
}

function renameChat(chatId: number, title: string) {
  const cleanTitle = title.trim();
  if (!cleanTitle) throw new Error("Informe um titulo valido.");
  connection().prepare("UPDATE chats SET title = ? WHERE id = ?").run(cleanTitle, chatId);
  return { success: true };
}

function deleteChat(chatId: number) {
  connection().prepare("DELETE FROM chats WHERE id = ?").run(chatId);
  return { success: true };
}

function listMessages(chatId: number, options: MessageOptions) {
  const limit = Math.min(Math.max(Number(options.limit ?? 500), 1), 2000);
  const offset = Math.max(Number(options.offset ?? 0), 0);
  return connection()
    .prepare("SELECT id, chat_id AS chatId, sender, body, sent_at AS sentAt, media_path AS mediaPath, raw_line AS rawLine FROM messages WHERE chat_id = ? ORDER BY id ASC LIMIT ? OFFSET ?")
    .all(chatId, limit, offset);
}

function searchMessages(query: string, options: SearchOptions) {
  const clean = query.trim();
  if (!clean) return [];
  const limit = Math.min(Math.max(Number(options.limit ?? 200), 1), 1000);
  const offset = Math.max(Number(options.offset ?? 0), 0);
  const db = connection();

  if (ftsAvailable()) {
    const sql = options.chatId
      ? `SELECT m.id, m.chat_id AS chatId, c.title AS chatTitle, m.sender, m.body, m.sent_at AS sentAt, m.media_path AS mediaPath
         FROM messages_fts f JOIN messages m ON m.id = f.rowid JOIN chats c ON c.id = m.chat_id
         WHERE messages_fts MATCH ? AND m.chat_id = ? ORDER BY m.id DESC LIMIT ? OFFSET ?`
      : `SELECT m.id, m.chat_id AS chatId, c.title AS chatTitle, m.sender, m.body, m.sent_at AS sentAt, m.media_path AS mediaPath
         FROM messages_fts f JOIN messages m ON m.id = f.rowid JOIN chats c ON c.id = m.chat_id
         WHERE messages_fts MATCH ? ORDER BY m.id DESC LIMIT ? OFFSET ?`;
    try {
      return options.chatId ? db.prepare(sql).all(clean, options.chatId, limit, offset) : db.prepare(sql).all(clean, limit, offset);
    } catch {
      // Fall back when the query contains FTS operators/syntax errors.
    }
  }

  const normalized = `%${normalizeSearchText(clean)}%`;
  const sql = options.chatId
    ? `SELECT m.id, m.chat_id AS chatId, c.title AS chatTitle, m.sender, m.body, m.sent_at AS sentAt, m.media_path AS mediaPath
       FROM messages m JOIN chats c ON c.id = m.chat_id
       WHERE m.chat_id = ? AND (m.body_search LIKE ? OR m.sender_search LIKE ?) ORDER BY m.id DESC LIMIT ? OFFSET ?`
    : `SELECT m.id, m.chat_id AS chatId, c.title AS chatTitle, m.sender, m.body, m.sent_at AS sentAt, m.media_path AS mediaPath
       FROM messages m JOIN chats c ON c.id = m.chat_id
       WHERE m.body_search LIKE ? OR m.sender_search LIKE ? ORDER BY m.id DESC LIMIT ? OFFSET ?`;
  return options.chatId ? db.prepare(sql).all(options.chatId, normalized, normalized, limit, offset) : db.prepare(sql).all(normalized, normalized, limit, offset);
}

async function openMedia(mediaPath: string) {
  if (!mediaPath || !existsSync(mediaPath)) throw new Error("Midia nao encontrada.");
  const error = await shell.openPath(mediaPath);
  if (error) throw new Error(error);
  return { success: true };
}
