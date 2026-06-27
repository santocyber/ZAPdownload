# AGENTS.md

## Scope
- This repo has two independent implementations of the same WhatsApp viewer: `zapviewer.py` at repo root and the PHP app under `wwwroot/`.
- Python data persists in `python_storage/`; PHP data persists in `wwwroot/storage/`. Do not delete or overwrite either storage unless explicitly asked.
- There is no Composer/npm/Python dependency manifest, CI config, or test runner; use direct syntax/check commands and manual browser/API verification.

## Commands
- Python app from repo root: `python3 zapviewer.py` then open `http://localhost:8001`.
- Python app on a custom port: `python3 zapviewer.py --port 8080`; env alternatives are `HOST` and `PORT`.
- Python storage/migration check: `python3 zapviewer.py --check`.
- PHP app from `wwwroot/`: `php -S localhost:8000 -t public` then open `http://localhost:8000`.
- PHP syntax check a touched file: `php -l path/to/file.php`.
- PHP syntax check all files from `wwwroot/`: `for f in public/*.php src/*.php; do php -l "$f" || exit 1; done`.

## Runtime Requirements
- Python version uses only the standard library and runs its own HTTP server; set a stable `ZAPVIEWER_SECRET` in deploy or sessions break on restart.
- PHP version requires PHP 8.1+ with `pdo_sqlite`; `.zip` imports require the `zip` extension (`ZipArchive`).
- Both implementations create storage directories and run SQLite migrations at startup/request time.

## Architecture Notes
- Python is monolithic: routes, HTML/CSS/JS, auth, chunk upload, import parsing, media serving, and SQLite migrations all live in `zapviewer.py`.
- PHP public web root must be `wwwroot/public`, not `wwwroot`; `wwwroot/storage/` must stay non-public.
- PHP browser entrypoint is `public/index.php`; frontend logic is plain JS in `public/app.js` and uses Resumable.js from jsDelivr.
- PHP endpoints are separate files: `public/api.php`, `public/upload-chunk.php`, `public/import.php`, `public/media.php`, `public/login.php`, `public/logout.php`, and `public/admin-users.php`.
- PHP shared constants/helpers and require-based loading live in `src/bootstrap.php`; auth is in `src/Auth.php`; schema/migrations are in `src/Database.php`; import parsing and ZIP media extraction are in `src/WhatsAppImporter.php`.

## Deployment Gotchas
- `wwwroot/nginx-site.example.conf` sets `root /var/www/zapviewer/wwwroot/public` and currently `client_max_body_size 20M`; browser uploads use 2 MB chunks while app-level max upload is 2 GB.
- Recommended deployed PHP storage permissions from `README.md`: `chown -R www-data:www-data /var/www/zapviewer/wwwroot/storage` and `chmod -R 775 /var/www/zapviewer/wwwroot/storage`.
- Media files are served only through application endpoints, which validate paths and user ownership.
