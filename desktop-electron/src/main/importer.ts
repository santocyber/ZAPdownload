import AdmZip from "adm-zip";
import mime from "mime-types";
import sanitize from "sanitize-filename";
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { basename, extname, join, normalize, relative } from "node:path";
import { randomUUID } from "node:crypto";
import { connection, normalizeSearchText } from "./database";
import { parseWhatsAppText, ParsedMessage } from "./parser";
import { ensureStorage } from "./storage";

const allowedExtensions = new Set([
  ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".3gp",
  ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".pdf", ".doc", ".docx", ".xls",
  ".xlsx", ".ppt", ".pptx", ".vcf", ".csv", ".txt",
]);

type PreparedImport = {
  title: string;
  sourceFile: string;
  text: string;
  mediaMap: Map<string, string>;
};

export type ImportResult = {
  chatId: number;
  title: string;
  messages: number;
};

export function importFile(filePath: string): ImportResult {
  const extension = extname(filePath).toLowerCase();
  if (![".txt", ".zip"].includes(extension)) {
    throw new Error("Formato invalido. Selecione um arquivo .txt ou .zip.");
  }

  const db = connection();
  const sourceFile = basename(filePath);
  const importRow = db.prepare("INSERT INTO imports (source_path, source_type, status) VALUES (?, ?, ?)").run(filePath, extension.slice(1), "running");

  try {
    const prepared = extension === ".zip" ? prepareZip(filePath) : prepareText(filePath);
    const messages = parseWhatsAppText(prepared.text);
    if (messages.length === 0) throw new Error("Nenhuma mensagem reconhecida no arquivo exportado.");

    const result = db.transaction(() => {
      const chatInfo = db
        .prepare("INSERT INTO chats (title, source_file, message_count, first_message_at, last_message_at) VALUES (?, ?, ?, ?, ?)")
        .run(
          prepared.title,
          prepared.sourceFile,
          messages.length,
          messages[0]?.sentAt ?? null,
          messages[messages.length - 1]?.sentAt ?? null,
        );
      const chatId = Number(chatInfo.lastInsertRowid);

      const insertMessage = db.prepare(`
        INSERT INTO messages (chat_id, sender, body, sender_search, body_search, sent_at, media_path, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `);
      const insertMedia = db.prepare(`
        INSERT INTO media (chat_id, original_name, stored_path, mime_type, size)
        VALUES (?, ?, ?, ?, ?)
      `);
      const mediaInserted = new Set<string>();

      for (const message of messages) {
        const mediaPath = findMediaPath(message, prepared.mediaMap);
        insertMessage.run(
          chatId,
          message.sender,
          message.body,
          normalizeSearchText(message.sender),
          normalizeSearchText(message.body),
          message.sentAt,
          mediaPath,
          message.rawLine,
        );

        if (mediaPath && !mediaInserted.has(mediaPath)) {
          mediaInserted.add(mediaPath);
          const original = [...prepared.mediaMap.entries()].find(([, stored]) => stored === mediaPath)?.[0] ?? basename(mediaPath);
          const size = existsSync(mediaPath) ? statSync(mediaPath).size : null;
          insertMedia.run(chatId, original, mediaPath, mime.lookup(mediaPath) || null, size);
        }
      }

      db.prepare("UPDATE imports SET chat_id = ?, status = ? WHERE id = ?").run(chatId, "done", importRow.lastInsertRowid);
      return { chatId, title: prepared.title, messages: messages.length };
    })();

    return result;
  } catch (error) {
    db.prepare("UPDATE imports SET status = ?, error = ? WHERE id = ?").run("error", error instanceof Error ? error.message : String(error), importRow.lastInsertRowid);
    throw error;
  }
}

function prepareText(filePath: string): PreparedImport {
  const paths = ensureStorage();
  const storedName = `${Date.now()}-${sanitize(basename(filePath))}`;
  const storedPath = join(paths.uploads, storedName);
  copyFileSync(filePath, storedPath);

  return {
    title: titleFromFilename(filePath),
    sourceFile: basename(filePath),
    text: readFileSync(storedPath, "utf8"),
    mediaMap: new Map(),
  };
}

function prepareZip(filePath: string): PreparedImport {
  const paths = ensureStorage();
  const importKey = `${Date.now()}-${randomUUID()}`;
  const extractRoot = join(paths.extracts, importKey);
  const mediaRoot = join(paths.media, importKey);
  mkdirSync(extractRoot, { recursive: true });
  mkdirSync(mediaRoot, { recursive: true });

  const zip = new AdmZip(filePath);
  const mediaMap = new Map<string, string>();
  let txtName: string | null = null;
  let txtContent: string | null = null;

  for (const entry of zip.getEntries()) {
    if (entry.isDirectory) continue;

    const entryName = normalize(entry.entryName).replace(/^([/\\])+/, "");
    if (entryName.includes("..")) continue;

    const safeBase = sanitize(basename(entryName));
    if (!safeBase) continue;

    const extension = extname(safeBase).toLowerCase();
    if (!allowedExtensions.has(extension)) continue;

    if (extension === ".txt" && txtContent === null) {
      txtName = safeBase;
      txtContent = entry.getData().toString("utf8");
      writeFileSync(safeJoin(extractRoot, safeBase), txtContent);
      continue;
    }

    if (extension !== ".txt") {
      const storedName = `${randomUUID()}-${safeBase}`;
      const storedPath = safeJoin(mediaRoot, storedName);
      writeFileSync(storedPath, entry.getData());
      mediaMap.set(safeBase, storedPath);
    }
  }

  if (!txtContent || !txtName) {
    throw new Error("O ZIP nao contem um arquivo .txt de conversa do WhatsApp.");
  }

  return {
    title: titleFromFilename(txtName),
    sourceFile: basename(filePath),
    text: txtContent,
    mediaMap,
  };
}

function safeJoin(root: string, child: string): string {
  const target = join(root, child);
  const diff = relative(root, target);
  if (diff.startsWith("..") || diff === "") throw new Error("Caminho invalido no arquivo importado.");
  return target;
}

function titleFromFilename(filePath: string): string {
  return basename(filePath, extname(filePath))
    .replace(/^Conversa do WhatsApp com\s+/i, "")
    .replace(/^WhatsApp Chat with\s+/i, "")
    .replace(/[_-]+/g, " ")
    .trim() || "Conversa importada";
}

function findMediaPath(message: ParsedMessage, mediaMap: Map<string, string>): string | null {
  for (const [name, stored] of mediaMap.entries()) {
    if (message.body.includes(name)) return stored;
  }
  return null;
}
