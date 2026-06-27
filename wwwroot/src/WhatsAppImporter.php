<?php
declare(strict_types=1);

final class WhatsAppImporter
{
    private const MEDIA_EXTENSIONS = [
        'jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'mov', 'm4v', '3gp',
        'mp3', 'm4a', 'opus', 'ogg', 'wav', 'pdf', 'doc', 'docx', 'xls',
        'xlsx', 'ppt', 'pptx', 'vcf', 'csv', 'txt'
    ];

    public function import(string $uploadedFilename): array
    {
        set_time_limit(0);

        $uploadedFilename = clean_filename($uploadedFilename);
        $uploadedPath = UPLOAD_DIR . '/' . $uploadedFilename;

        if (!is_file($uploadedPath)) {
            throw new RuntimeException('Arquivo enviado nao foi encontrado.');
        }

        if (!allowed_upload_extension($uploadedFilename)) {
            throw new RuntimeException('Formato invalido. Envie um arquivo .txt ou .zip.');
        }

        $userId = current_user_id();

        if ($userId === null) {
            throw new RuntimeException('Login necessario para importar.');
        }

        if (!str_starts_with($uploadedFilename, 'u' . $userId . '_')) {
            throw new RuntimeException('Arquivo enviado nao pertence ao usuario logado.');
        }

        $extension = strtolower(pathinfo($uploadedFilename, PATHINFO_EXTENSION));
        $importKey = $this->makeImportKey($uploadedFilename);
        $prepared = $extension === 'zip'
            ? $this->prepareZip($uploadedPath, $importKey)
            : ['txtPath' => $uploadedPath, 'mediaMap' => []];

        $txtPath = $prepared['txtPath'];
        $mediaMap = $prepared['mediaMap'];
        $title = $this->makeConversationTitle($txtPath, $uploadedFilename);

        $db = Database::connection();
        $db->beginTransaction();

        try {
            $conversationStmt = $db->prepare(
                'INSERT INTO conversations (user_id, title, source_file, imported_at) VALUES (:user_id, :title, :source_file, :imported_at)'
            );
            $conversationStmt->execute([
                ':user_id' => $userId,
                ':title' => $title,
                ':source_file' => $uploadedFilename,
                ':imported_at' => gmdate('Y-m-d H:i:s'),
            ]);

            $conversationId = (int) $db->lastInsertId();
            $count = $this->importTextFile($txtPath, $conversationId, $mediaMap);

            $updateStmt = $db->prepare('UPDATE conversations SET message_count = :count WHERE id = :id');
            $updateStmt->execute([
                ':count' => $count,
                ':id' => $conversationId,
            ]);

            $db->commit();
        } catch (Throwable $exception) {
            $db->rollBack();
            throw $exception;
        }

        return [
            'conversation_id' => $conversationId,
            'title' => $title,
            'messages' => $count,
        ];
    }

    private function importTextFile(string $txtPath, int $conversationId, array $mediaMap): int
    {
        $handle = fopen($txtPath, 'rb');

        if ($handle === false) {
            throw new RuntimeException('Nao foi possivel abrir o TXT exportado.');
        }

        $db = Database::connection();
        $insertStmt = $db->prepare(<<<'SQL'
INSERT INTO messages (conversation_id, sender, body, sender_search, body_search, sent_at, media_path, raw_line)
VALUES (:conversation_id, :sender, :body, :sender_search, :body_search, :sent_at, :media_path, :raw_line)
SQL);

        $count = 0;
        $lineNumber = 0;
        $pending = null;

        while (($line = fgets($handle)) !== false) {
            $lineNumber++;
            $line = rtrim($line, "\r\n");

            if ($lineNumber === 1) {
                $line = preg_replace('/^\xEF\xBB\xBF/', '', $line) ?? $line;
            }

            $message = $this->parseMessageLine($line);

            if ($message !== null) {
                if ($pending !== null) {
                    $this->insertMessage($insertStmt, $conversationId, $pending, $mediaMap);
                    $count++;
                }

                $message['raw_line'] = $lineNumber;
                $pending = $message;
                continue;
            }

            if ($pending !== null) {
                $pending['body'] .= "\n" . $line;
            }
        }

        if ($pending !== null) {
            $this->insertMessage($insertStmt, $conversationId, $pending, $mediaMap);
            $count++;
        }

        fclose($handle);

        return $count;
    }

    private function insertMessage(PDOStatement $stmt, int $conversationId, array $message, array $mediaMap): void
    {
        $mediaPath = $this->findMediaPath($message['body'], $mediaMap);

        $stmt->execute([
            ':conversation_id' => $conversationId,
            ':sender' => $message['sender'],
            ':body' => $message['body'],
            ':sender_search' => normalize_search_text($message['sender'] ?? ''),
            ':body_search' => normalize_search_text($message['body']),
            ':sent_at' => $message['sent_at'],
            ':media_path' => $mediaPath,
            ':raw_line' => $message['raw_line'],
        ]);
    }

    private function parseMessageLine(string $line): ?array
    {
        $patterns = [
            '/^\[(?<date>\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4}),?\s+(?<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?<ampm>[AP]\.?M\.?)?\]\s*(?<body>.*)$/iu',
            '/^(?<date>\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4}),?\s+(?<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?<ampm>[AP]\.?M\.?)?\s+-\s*(?<body>.*)$/iu',
        ];

        foreach ($patterns as $pattern) {
            if (!preg_match($pattern, $line, $matches)) {
                continue;
            }

            $sentAt = $this->normalizeDateTime($matches['date'], $matches['time'], $matches['ampm'] ?? null);

            if ($sentAt === null) {
                return null;
            }

            [$sender, $body] = $this->splitSenderAndBody($matches['body']);

            return [
                'sender' => $sender,
                'body' => $body,
                'sent_at' => $sentAt,
            ];
        }

        return null;
    }

    private function splitSenderAndBody(string $body): array
    {
        $separatorPosition = strpos($body, ': ');

        if ($separatorPosition === false) {
            return [null, trim($body)];
        }

        $sender = trim(substr($body, 0, $separatorPosition));
        $messageBody = trim(substr($body, $separatorPosition + 2));

        return [$sender !== '' ? $sender : null, $messageBody];
    }

    private function normalizeDateTime(string $date, string $time, ?string $ampm): ?string
    {
        $dateParts = preg_split('/[\/.\-]/', $date);
        $timeParts = explode(':', $time);

        if (count($dateParts) !== 3 || count($timeParts) < 2) {
            return null;
        }

        $first = (int) $dateParts[0];
        $second = (int) $dateParts[1];
        $year = (int) $dateParts[2];

        if ($year < 100) {
            $year += $year >= 70 ? 1900 : 2000;
        }

        if ($second > 12 && $first <= 12) {
            $month = $first;
            $day = $second;
        } else {
            $day = $first;
            $month = $second;
        }

        if (!checkdate($month, $day, $year) && checkdate($day, $month, $year)) {
            [$day, $month] = [$month, $day];
        }

        if (!checkdate($month, $day, $year)) {
            return null;
        }

        $hour = (int) $timeParts[0];
        $minute = (int) $timeParts[1];
        $secondValue = isset($timeParts[2]) ? (int) $timeParts[2] : 0;

        if ($ampm !== null && trim($ampm) !== '') {
            $ampm = strtoupper(str_replace('.', '', $ampm));

            if ($ampm === 'PM' && $hour < 12) {
                $hour += 12;
            }

            if ($ampm === 'AM' && $hour === 12) {
                $hour = 0;
            }
        }

        if ($hour > 23 || $minute > 59 || $secondValue > 59) {
            return null;
        }

        return sprintf('%04d-%02d-%02d %02d:%02d:%02d', $year, $month, $day, $hour, $minute, $secondValue);
    }

    private function prepareZip(string $zipPath, string $importKey): array
    {
        if (!class_exists('ZipArchive')) {
            throw new RuntimeException('A extensao PHP zip nao esta habilitada. Importe .txt ou habilite zip.');
        }

        $zip = new ZipArchive();

        if ($zip->open($zipPath) !== true) {
            throw new RuntimeException('Nao foi possivel abrir o arquivo ZIP.');
        }

        $extractDir = EXTRACT_DIR . '/' . $importKey;
        $mediaDir = MEDIA_DIR . '/' . $importKey;

        if (!is_dir($extractDir)) {
            mkdir($extractDir, 0775, true);
        }

        if (!is_dir($mediaDir)) {
            mkdir($mediaDir, 0775, true);
        }

        $txtFiles = [];
        $mediaMap = [];

        for ($i = 0; $i < $zip->numFiles; $i++) {
            $stat = $zip->statIndex($i);
            $entryName = is_array($stat) ? (string) ($stat['name'] ?? '') : '';
            $entrySize = is_array($stat) ? (int) ($stat['size'] ?? 0) : 0;

            if ($entryName === '' || str_ends_with($entryName, '/')) {
                continue;
            }

            $entryName = str_replace('\\', '/', $entryName);

            if (!$this->isSafeZipEntry($entryName)) {
                throw new RuntimeException('ZIP contem caminho inseguro: ' . $entryName);
            }

            $extension = strtolower(pathinfo($entryName, PATHINFO_EXTENSION));

            if (!in_array($extension, self::MEDIA_EXTENSIONS, true)) {
                continue;
            }

            $originalBase = basename($entryName);
            $targetDir = $extension === 'txt' ? $extractDir : $mediaDir;
            $targetName = $this->uniqueFilename($targetDir, $originalBase);
            $targetPath = $targetDir . '/' . $targetName;

            if (!$this->copyZipEntry($zip, $entryName, $targetPath)) {
                continue;
            }

            if ($extension === 'txt') {
                $txtFiles[] = [
                    'path' => $targetPath,
                    'size' => $entrySize,
                ];
                continue;
            }

            $mediaMap[strtolower($originalBase)] = $importKey . '/' . $targetName;
        }

        $zip->close();

        if ($txtFiles === []) {
            throw new RuntimeException('Nenhum arquivo .txt foi encontrado dentro do ZIP.');
        }

        usort($txtFiles, static fn (array $a, array $b): int => $b['size'] <=> $a['size']);

        return [
            'txtPath' => $txtFiles[0]['path'],
            'mediaMap' => $mediaMap,
        ];
    }

    private function copyZipEntry(ZipArchive $zip, string $entryName, string $targetPath): bool
    {
        $input = $zip->getStream($entryName);

        if ($input === false) {
            return false;
        }

        $output = fopen($targetPath, 'wb');

        if ($output === false) {
            fclose($input);
            return false;
        }

        stream_copy_to_stream($input, $output);
        fclose($input);
        fclose($output);

        return true;
    }

    private function isSafeZipEntry(string $entryName): bool
    {
        if (str_contains($entryName, "\0") || str_starts_with($entryName, '/') || preg_match('/^[A-Za-z]:/', $entryName)) {
            return false;
        }

        foreach (explode('/', $entryName) as $part) {
            if ($part === '..') {
                return false;
            }
        }

        return true;
    }

    private function uniqueFilename(string $directory, string $filename): string
    {
        $filename = clean_filename($filename);
        $extension = pathinfo($filename, PATHINFO_EXTENSION);
        $name = pathinfo($filename, PATHINFO_FILENAME);
        $candidate = $filename;
        $index = 1;

        while (file_exists($directory . '/' . $candidate)) {
            $candidate = $name . '_' . $index . ($extension !== '' ? '.' . $extension : '');
            $index++;
        }

        return $candidate;
    }

    private function findMediaPath(string $body, array $mediaMap): ?string
    {
        if ($mediaMap === []) {
            return null;
        }

        if (!preg_match_all('/([A-Za-z0-9._() @-]+?\.(?:jpe?g|png|gif|webp|mp4|mov|m4v|3gp|mp3|m4a|opus|ogg|wav|pdf|docx?|xlsx?|pptx?|vcf|csv))/iu', $body, $matches)) {
            return null;
        }

        foreach ($matches[1] as $match) {
            $key = strtolower(basename(trim($match)));

            if (isset($mediaMap[$key])) {
                return $mediaMap[$key];
            }
        }

        return null;
    }

    private function makeImportKey(string $uploadedFilename): string
    {
        $base = strtolower(pathinfo($uploadedFilename, PATHINFO_FILENAME));
        $base = preg_replace('/[^a-z0-9_-]/', '_', $base) ?? 'import';
        $base = trim($base, '_-') ?: 'import';

        return substr($base, 0, 80) . '_' . bin2hex(random_bytes(4));
    }

    private function makeConversationTitle(string $txtPath, string $sourceFile): string
    {
        $base = pathinfo($txtPath, PATHINFO_FILENAME) ?: pathinfo($sourceFile, PATHINFO_FILENAME);
        $base = preg_replace('/^Conversa do WhatsApp com\s+/iu', '', $base) ?? $base;
        $base = preg_replace('/^WhatsApp Chat(?: with)?\s+/iu', '', $base) ?? $base;
        $base = str_replace(['_', '-'], ' ', $base);
        $base = trim(preg_replace('/\s+/', ' ', $base) ?? $base);

        return $base !== '' ? $base : 'Conversa importada';
    }
}
