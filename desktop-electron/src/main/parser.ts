import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";

dayjs.extend(customParseFormat);

export type ParsedMessage = {
  sender: string | null;
  body: string;
  sentAt: string | null;
  rawLine: number;
};

type PendingMessage = ParsedMessage | null;

const linePatterns = [
  /^\[(?<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(?<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?<ampm>[AP]\.?M\.?)?\]\s*(?<body>.*)$/iu,
  /^(?<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(?<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?<ampm>[AP]\.?M\.?)?\s+-\s*(?<body>.*)$/iu,
];

export function parseWhatsAppText(text: string): ParsedMessage[] {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
  const messages: ParsedMessage[] = [];
  let pending: PendingMessage = null;

  lines.forEach((rawLine, index) => {
    const lineNumber = index + 1;
    const parsed = parseMessageLine(rawLine, lineNumber);

    if (parsed) {
      if (pending) messages.push(pending);
      pending = parsed;
      return;
    }

    if (pending) pending.body += `\n${rawLine}`;
  });

  if (pending) messages.push(pending);
  return messages;
}

function parseMessageLine(line: string, rawLine: number): ParsedMessage | null {
  for (const pattern of linePatterns) {
    const match = line.match(pattern);
    if (!match?.groups) continue;

    const sentAt = normalizeDateTime(match.groups.date, match.groups.time, match.groups.ampm);
    if (!sentAt) continue;

    const [sender, body] = splitSenderAndBody(match.groups.body ?? "");
    return { sender, body, sentAt, rawLine };
  }

  return null;
}

function splitSenderAndBody(value: string): [string | null, string] {
  const separator = value.indexOf(": ");
  if (separator === -1) return [null, value.trim()];

  const sender = value.slice(0, separator).trim();
  const body = value.slice(separator + 2).trim();
  return [sender || null, body];
}

function normalizeDateTime(date: string, time: string, ampm?: string): string | null {
  const parts = date.split(/[/.\-]/).map((part) => Number.parseInt(part, 10));
  if (parts.length !== 3 || parts.some(Number.isNaN)) return null;

  let [first, second, year] = parts;
  if (year < 100) year += year >= 70 ? 1900 : 2000;

  let day = first;
  let month = second;
  if (second > 12 && first <= 12) {
    month = first;
    day = second;
  }

  const cleanAmpm = ampm?.replace(/\./g, "").toUpperCase();
  const value = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")} ${time}${cleanAmpm ? ` ${cleanAmpm}` : ""}`;
  const formats = cleanAmpm ? ["YYYY-MM-DD h:mm:ss A", "YYYY-MM-DD h:mm A"] : ["YYYY-MM-DD H:mm:ss", "YYYY-MM-DD H:mm"];
  const parsed = dayjs(value, formats, true);

  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm:ss") : null;
}
