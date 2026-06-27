# WhatsApp Export Viewer

Aplicacao web local em PHP + JavaScript para importar exportacoes do WhatsApp, visualizar conversas, pesquisar mensagens e abrir midias anexadas.

## Funcionalidades

- Importacao de exportacoes `.txt` do WhatsApp.
- Importacao de exportacoes `.zip`, incluindo midias quando a extensao PHP `zip` estiver habilitada.
- Upload em partes com Resumable.js para arquivos grandes.
- Login local com criacao do primeiro admin na primeira abertura.
- Cadastro e manutencao de usuarios por admins.
- Conversas, uploads e midias vinculados ao usuario logado.
- Busca geral e busca por conversa, com filtros de data.
- Persistencia local em SQLite.

## Requisitos

- PHP 8.1 ou superior.
- Extensao PHP `pdo_sqlite`.
- Extensao PHP `zip` para importar arquivos `.zip`.

Nao ha dependencias Composer ou npm neste projeto.

## Como Rodar Localmente

Execute a partir desta pasta `wwwroot/`:

```bash
php -S localhost:8000 -t public
```

Acesse no navegador:

```text
http://localhost:8000
```

O servidor deve apontar para `public/`, nunca para a raiz `wwwroot/`, porque `storage/` guarda banco, uploads e midias importadas.

## Primeiro Acesso

1. Abra `http://localhost:8000`.
2. Como nao existe usuario, a tela `login.php` pede a criacao do primeiro admin.
3. Depois de logado, use o viewer para importar conversas.
4. Se for admin, acesse `admin-users.php` pelo link `Admin` para criar ou alterar usuarios.

Usuarios comuns acessam apenas as proprias conversas. Admins tambem acessam apenas as proprias conversas no viewer, mas podem gerenciar usuarios.

## Como Usar

1. Exporte uma conversa no WhatsApp como `.txt` ou `.zip`.
2. Entre na aplicacao com seu usuario.
3. Arraste o arquivo para a area de upload ou clique em `Escolher`.
4. Clique em `Enviar`.
5. Aguarde o upload, a montagem dos chunks e a importacao.
6. Selecione a conversa importada na lateral para visualizar as mensagens.
7. Use a busca geral, a busca do chat e os filtros de data quando precisar localizar mensagens.

## Estrutura

```text
wwwroot/
  public/                 Frontend e endpoints publicos
    index.php             Entrada do viewer, exige login
    login.php             Login e criacao do primeiro admin
    logout.php            Encerramento da sessao
    admin-users.php       Gerenciamento de usuarios por admin
    app.js                Logica da interface
    api.php               API de conversas, mensagens, busca e exclusao
    upload-chunk.php      Upload em partes
    import.php            Importacao apos upload
    media.php             Entrega segura de midias
  src/
    bootstrap.php         Constantes, helpers, setup de storage e migracoes
    Auth.php              Sessao, login, CSRF, roles e usuarios
    Database.php          Conexao SQLite e schema
    WhatsAppImporter.php  Parser do export do WhatsApp e extracao de ZIP
  storage/                Banco SQLite, uploads, chunks, midias e extracoes
```

`src/bootstrap.php` cria automaticamente as pastas de `storage/` e executa as migracoes SQLite a cada request.

## Dados Persistidos

Os dados ficam em:

```text
storage/database.sqlite
storage/uploads/
storage/chunks/
storage/media/
storage/extracts/
```

Evite apagar `storage/` se quiser manter usuarios, conversas importadas, uploads e midias.

## Verificacao

Para validar a sintaxe de todos os arquivos PHP, execute em `wwwroot/`:

```bash
for f in public/*.php src/*.php; do php -l "$f" || exit 1; done
```

Para validar apenas um arquivo alterado:

```bash
php -l public/api.php
```

## Deploy Em VPS Com Nginx

Envie a pasta `wwwroot/` para a VPS, por exemplo:

```text
/var/www/zapviewer/wwwroot
```

No Nginx, aponte o `root` para `public/`:

```text
root /var/www/zapviewer/wwwroot/public;
```

Existe um exemplo em `nginx-site.example.conf`. Ajuste `server_name`, caminho do projeto e socket do PHP-FPM conforme sua VPS.

Permissoes recomendadas para a pasta de dados:

```bash
chown -R www-data:www-data /var/www/zapviewer/wwwroot/storage
chmod -R 775 /var/www/zapviewer/wwwroot/storage
```

O exemplo de Nginx define `client_max_body_size 20M`. O navegador envia chunks de 2 MB e o PHP aceita ate 2 GB no total por `MAX_UPLOAD_BYTES`, entao ajuste esse limite se mudar o tamanho dos chunks ou a estrategia de upload.

## Seguranca

- Mantenha `storage/` fora do web root publico.
- Aceite apenas uploads `.txt` e `.zip`.
- Arquivos dentro de ZIP com caminhos inseguros sao bloqueados.
- Endpoints do viewer exigem login.
- Formularios sensiveis usam token CSRF.
- Midias importadas sao servidas apenas por `public/media.php`, com validacao de caminho e pertencimento ao usuario logado.
