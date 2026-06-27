<?php
declare(strict_types=1);

const APP_ROOT = __DIR__ . '/..';
const STORAGE_DIR = APP_ROOT . '/storage';
const UPLOAD_DIR = STORAGE_DIR . '/uploads';
const CHUNK_DIR = STORAGE_DIR . '/chunks';
const MEDIA_DIR = STORAGE_DIR . '/media';
const EXTRACT_DIR = STORAGE_DIR . '/extracts';
const DB_PATH = STORAGE_DIR . '/database.sqlite';
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024;

foreach ([STORAGE_DIR, UPLOAD_DIR, CHUNK_DIR, MEDIA_DIR, EXTRACT_DIR] as $directory) {
    if (!is_dir($directory)) {
        mkdir($directory, 0775, true);
    }
}

function normalize_search_text(?string $value): string
{
    $text = trim((string) $value);

    if ($text === '') {
        return '';
    }

    if (function_exists('iconv')) {
        $converted = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);

        if (is_string($converted) && $converted !== '') {
            $text = $converted;
        }
    } else {
        $text = strtr($text, search_accent_map());
    }

    $text = strtolower($text);
    $text = preg_replace('/[^a-z0-9]+/', ' ', $text) ?? $text;
    $text = preg_replace('/\s+/', ' ', $text) ?? $text;

    return trim($text);
}

function search_terms(string $query): array
{
    $normalized = normalize_search_text($query);

    if ($normalized === '') {
        return [];
    }

    $terms = preg_split('/\s+/', $normalized) ?: [];
    $terms = array_filter($terms, static fn (string $term): bool => strlen($term) >= 2);

    return array_values(array_unique($terms));
}

function search_accent_map(): array
{
    static $map = null;

    if ($map !== null) {
        return $map;
    }

    $entities = [
        '&Aacute;' => 'a', '&Agrave;' => 'a', '&Acirc;' => 'a', '&Atilde;' => 'a', '&Auml;' => 'a', '&aacute;' => 'a', '&agrave;' => 'a', '&acirc;' => 'a', '&atilde;' => 'a', '&auml;' => 'a',
        '&Eacute;' => 'e', '&Egrave;' => 'e', '&Ecirc;' => 'e', '&Euml;' => 'e', '&eacute;' => 'e', '&egrave;' => 'e', '&ecirc;' => 'e', '&euml;' => 'e',
        '&Iacute;' => 'i', '&Igrave;' => 'i', '&Icirc;' => 'i', '&Iuml;' => 'i', '&iacute;' => 'i', '&igrave;' => 'i', '&icirc;' => 'i', '&iuml;' => 'i',
        '&Oacute;' => 'o', '&Ograve;' => 'o', '&Ocirc;' => 'o', '&Otilde;' => 'o', '&Ouml;' => 'o', '&oacute;' => 'o', '&ograve;' => 'o', '&ocirc;' => 'o', '&otilde;' => 'o', '&ouml;' => 'o',
        '&Uacute;' => 'u', '&Ugrave;' => 'u', '&Ucirc;' => 'u', '&Uuml;' => 'u', '&uacute;' => 'u', '&ugrave;' => 'u', '&ucirc;' => 'u', '&uuml;' => 'u',
        '&Ccedil;' => 'c', '&ccedil;' => 'c', '&Ntilde;' => 'n', '&ntilde;' => 'n',
    ];

    $map = [];

    foreach ($entities as $entity => $replacement) {
        $map[html_entity_decode($entity, ENT_QUOTES | ENT_HTML5, 'UTF-8')] = $replacement;
    }

    return $map;
}

require_once __DIR__ . '/Database.php';
require_once __DIR__ . '/Auth.php';
require_once __DIR__ . '/WhatsAppImporter.php';

Database::migrate();

function json_response(array $payload, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function fail_response(string $message, int $status = 400, array $extra = []): void
{
    json_response(array_merge([
        'success' => false,
        'error' => $message,
    ], $extra), $status);
}

function request_json(): array
{
    $raw = file_get_contents('php://input');

    if ($raw === false || trim($raw) === '') {
        return [];
    }

    $decoded = json_decode($raw, true);

    return is_array($decoded) ? $decoded : [];
}

function clean_identifier(string $identifier): string
{
    $identifier = preg_replace('/[^A-Za-z0-9_-]/', '', $identifier) ?? '';
    return substr($identifier, 0, 160);
}

function clean_filename(string $filename): string
{
    $filename = basename(str_replace('\\', '/', $filename));
    $filename = preg_replace('/[^A-Za-z0-9._ -]/', '_', $filename) ?? 'upload';
    $filename = trim($filename, ' ._');

    return $filename !== '' ? $filename : 'upload';
}

function allowed_upload_extension(string $filename): bool
{
    return in_array(strtolower(pathinfo($filename, PATHINFO_EXTENSION)), ['txt', 'zip'], true);
}

function int_param(string $key, int $default = 0): int
{
    $value = $_REQUEST[$key] ?? $default;
    return is_numeric($value) ? (int) $value : $default;
}

function text_param(string $key, string $default = ''): string
{
    $value = $_REQUEST[$key] ?? $default;
    return is_string($value) ? $value : $default;
}
