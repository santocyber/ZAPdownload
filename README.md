# WhatsApp Export Viewer

Aplicacao local para importar exportacoes do WhatsApp (`.txt` ou `.zip`), visualizar conversas, pesquisar mensagens e abrir midias anexadas.

O repositorio contem tres implementacoes independentes do mesmo viewer:

- `desktop-electron/`: app desktop standalone com Electron, sem login, sem Python/PHP e sem navegador externo.
- `zapviewer.py`: versao Python monolitica, sem dependencias externas, com servidor HTTP proprio.
- `wwwroot/`: versao PHP + JavaScript para rodar com servidor PHP embutido, Nginx ou PHP-FPM.

As tres versoes usam bancos e storages separados. Dados importados em uma versao nao aparecem automaticamente nas outras.

## App Desktop Standalone

A versao desktop fica em `desktop-electron/` e gera pacotes locais para Windows, macOS e Linux:

```text
ZapViewer-Windows.exe
ZapViewer-macOS.dmg
ZapViewer-Linux.AppImage
```

Caracteristicas:

- Interface desktop propria com Electron e Chromium embutido.
- Nao precisa Python, PHP, Apache, Nginx ou navegador externo.
- Funciona offline.
- Nao tem login; e um app local para uso pessoal.
- Importa exports `.txt` e `.zip` do WhatsApp.
- Extrai midias de `.zip` e abre arquivos locais.
- Usa SQLite local.
- Tem tema claro, escuro e automatico pelo sistema.

Para desenvolvimento:

```bash
cd desktop-electron
npm ci
npm run dev
```

Para gerar o pacote do sistema atual:

```bash
npm run dist
```

Cada sistema deve gerar seu proprio pacote:

- Windows gera `release/ZapViewer-Windows.exe`.
- macOS gera `release/ZapViewer-macOS.dmg`.
- Linux gera `release/ZapViewer-Linux.AppImage`.

Tambem existe um workflow em `.github/workflows/desktop-electron-release.yml` para gerar os tres pacotes automaticamente em GitHub Actions.

## Baixar E Executar Rapido Com Python

Clone o repositorio:

```bash
git clone https://github.com/santocyber/ZAPdownload.git
cd ZAPdownload
```

Verifique/crie o banco e as pastas locais:

```bash
python3 zapviewer.py --check
```

Inicie o servidor Python:

```bash
python3 zapviewer.py
```

Acesse no navegador:

```text
http://localhost:8001
```

A versao Python nao precisa instalar dependencias externas. Ela usa apenas a biblioteca padrao do Python e salva os dados em `python_storage/`.

## Funcionalidades

Desktop Electron:

- App standalone sem navegador externo.
- Importacao de exports `.txt` e `.zip`.
- Extracao de midias de arquivos `.zip`.
- Busca de mensagens.
- Persistencia local em SQLite.
- Tema claro, escuro e automatico.
- Sem login e sem usuarios.

Versoes Python/PHP:

- Importacao de exports `.txt` do WhatsApp.
- Importacao de exports `.zip` com extracao de midias.
- Upload em chunks de 2 MB para arquivos grandes.
- Login local e criacao do primeiro admin no primeiro acesso.
- Gerenciamento de usuarios por admin.
- Conversas, uploads e midias vinculados ao usuario logado.
- Busca geral e busca dentro do chat, com filtros de data.
- Mensagens ordenadas das mais recentes para as mais antigas.
- Paginacao com carregamento sob demanda em lotes de 2000 mensagens.
- Botao "Carregar mensagens mais antigas" para navegar pelo historico completo.
- Persistencia em SQLite.
- Midias servidas por endpoint protegido, com validacao de caminho e usuario.

## Escolha Da Versao

Use a versao desktop Electron se quiser um aplicativo standalone, offline, sem login, sem Python/PHP e sem abrir navegador externo.

Use a versao Python se quiser rodar tudo com um unico arquivo e sem configurar PHP/Nginx.

Use a versao PHP se quiser deploy em hospedagem ou VPS com PHP-FPM/Nginx.

## Rodar A Versao Desktop Electron

Requisitos para desenvolvimento/build:

- Node.js 20+ ou 22+.
- npm.
- Git.
- No macOS, `xcode-select --install`.
- No Windows, Visual Studio Build Tools pode ser necessario se `better-sqlite3` precisar compilar.

Instale dependencias:

```bash
cd desktop-electron
npm ci
```

Rode em modo desenvolvimento:

```bash
npm run dev
```

Gere o pacote do sistema atual:

```bash
npm run dist
```

Saidas esperadas:

```text
desktop-electron/release/ZapViewer-Windows.exe
desktop-electron/release/ZapViewer-macOS.dmg
desktop-electron/release/ZapViewer-Linux.AppImage
```

Observacao: o pacote macOS deve ser gerado no macOS. O pacote Windows e mais confiavel quando gerado no Windows, principalmente por causa de dependencias nativas como `better-sqlite3`.

## Rodar A Versao Python

Requisitos:

- Python 3.10+ recomendado.
- Nenhuma dependencia externa.

Comando basico, a partir da raiz do repositorio:

```bash
python3 zapviewer.py
```

Por padrao, o servidor usa `HOST=0.0.0.0` e `PORT=8001`:

```text
http://localhost:8001
```

Para escolher a porta:

```bash
python3 zapviewer.py --port 8080
```

Tambem e possivel usar variaveis de ambiente:

```bash
HOST=127.0.0.1 PORT=8080 python3 zapviewer.py
```

Para preparar/verificar banco e pastas sem iniciar o servidor:

```bash
python3 zapviewer.py --check
```

Para manter sessoes validas entre reinicios em deploy, defina um segredo fixo:

```bash
ZAPVIEWER_SECRET="troque-por-um-segredo-longo" python3 zapviewer.py
```

Sem `ZAPVIEWER_SECRET`, o Python gera um segredo novo a cada inicio e os cookies de sessao antigos deixam de validar.

## Rodar A Versao PHP

Requisitos:

- PHP 8.1+.
- Extensao PHP `pdo_sqlite`.
- Extensao PHP `zip` para importar `.zip`.

Nao ha Composer nem npm neste projeto.

Execute a partir de `wwwroot/`:

```bash
php -S localhost:8000 -t public
```

Acesse:

```text
http://localhost:8000
```

O web root deve ser sempre `wwwroot/public`, nunca `wwwroot`, porque `storage/` guarda banco, uploads e midias.

## Primeiro Acesso

1. Abra a URL da versao escolhida.
2. Como nao existe usuario, a tela de login pede a criacao do primeiro admin.
3. Depois de logado, importe conversas no viewer.
4. Se for admin, use a tela `Admin` para criar, ativar, desativar ou alterar usuarios.

Usuarios comuns acessam apenas as proprias conversas. Admins tambem acessam apenas as proprias conversas no viewer, mas podem gerenciar usuarios.

## Como Importar Conversas

Desktop Electron:

1. Abra o app desktop.
2. Clique em `Importar .txt ou .zip`.
3. Selecione o export do WhatsApp.
4. Aguarde a importacao local.
5. Abra a conversa na lateral, pesquise mensagens e abra midias quando necessario.

Python/PHP:

1. No WhatsApp, exporte uma conversa como `.txt` ou `.zip`.
2. Use `.txt` para importar apenas mensagens.
3. Use `.zip` para importar mensagens e midias exportadas.
4. Entre no viewer com seu usuario.
5. Arraste o arquivo para a area de upload ou clique em `Escolher`.
6. Clique em `Enviar`.
7. Aguarde upload, montagem dos chunks e importacao.
8. Abra a conversa na lateral e use busca/filtros conforme necessario.

## Storage E Banco

Versao Desktop Electron:

Windows:

```text
C:\Users\Usuario\AppData\Roaming\ZapViewer\
```

macOS:

```text
~/Library/Application Support/ZapViewer/
```

Linux:

```text
~/.config/ZapViewer/
```

Conteudo principal:

```text
database.sqlite
uploads/
extracts/
media/
temp/
backups/
```

Versao Python:

```text
python_storage/database.sqlite
python_storage/uploads/
python_storage/chunks/
python_storage/media/
python_storage/extracts/
```

Versao PHP:

```text
wwwroot/storage/database.sqlite
wwwroot/storage/uploads/
wwwroot/storage/chunks/
wwwroot/storage/media/
wwwroot/storage/extracts/
```

Evite apagar essas pastas se quiser manter usuarios, sessoes, conversas, uploads e midias importadas. Na versao desktop, apagar a pasta de dados local remove as conversas importadas do app.

## Estrutura Do Projeto

```text
.
  desktop-electron/         App desktop standalone com Electron
    package.json            Scripts, dependencias e config do electron-builder
    src/
      main/                 Processo principal, SQLite, importador e IPC
      preload/              Ponte segura entre Electron e interface
      renderer/             Interface desktop
    release/                Pacotes gerados localmente, ignorados pelo Git
  .github/workflows/
    desktop-electron-release.yml  Build dos pacotes desktop no GitHub Actions
  zapviewer.py              Versao Python monolitica
  python_storage/           Dados persistidos da versao Python
  wwwroot/
    public/                 Web root da versao PHP
      index.php             Viewer autenticado
      login.php             Login e criacao do primeiro admin
      admin-users.php       Gerenciamento de usuarios
      api.php               Conversas, mensagens, busca e exclusao
      upload-chunk.php      Upload em chunks
      import.php            Importacao apos upload
      media.php             Entrega segura de midias
      app.js                Frontend do viewer PHP
      style.css             Estilos do viewer PHP
    src/
      bootstrap.php         Constantes, helpers, storage e migracoes
      Auth.php              Sessao, login, roles e CSRF
      Database.php          Conexao SQLite e schema
      WhatsAppImporter.php  Parser do WhatsApp e extracao ZIP
    storage/                Dados persistidos da versao PHP
```

## Verificacao

Desktop Electron, a partir de `desktop-electron/`:

```bash
npm run typecheck
npm run build
```

Gerar pacote local:

```bash
npm run dist
```

Python:

```bash
python3 zapviewer.py --check
```

PHP, a partir de `wwwroot/`:

```bash
for f in public/*.php src/*.php; do php -l "$f" || exit 1; done
```

Validar apenas um arquivo PHP alterado:

```bash
php -l public/api.php
```

## Releases Desktop

O workflow `Desktop Electron Release` roda em tags `v*` e tambem pode ser iniciado manualmente pelo GitHub Actions.

Para criar uma release por tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

O workflow usa:

```text
windows-latest -> ZapViewer-Windows.exe
macos-latest   -> ZapViewer-macOS.dmg
ubuntu-latest  -> ZapViewer-Linux.AppImage
```

Os artefatos sao enviados para a release quando a tag e publicada.

## Problemas Comuns No Desktop

macOS:

```bash
xcode-select --install
npm rebuild better-sqlite3
npm run dist
```

Se o macOS bloquear o app por falta de assinatura, use `Botao direito > Abrir` ou autorize em `Ajustes do Sistema > Privacidade e Seguranca`.

Windows:

- Use Node.js LTS.
- Se `better-sqlite3` falhar, instale Visual Studio Build Tools com `Desktop development with C++`.
- O SmartScreen pode alertar executaveis nao assinados.

Linux:

- O AppImage e gerado por `npm run dist`.
- Algumas distribuicoes podem exigir bibliotecas graficas basicas do Electron.

## Deploy PHP Com Nginx

Envie `wwwroot/` para a VPS, por exemplo:

```text
/var/www/zapviewer/wwwroot
```

Configure o Nginx com root em `public/`:

```text
root /var/www/zapviewer/wwwroot/public;
```

Existe um exemplo em:

```text
wwwroot/nginx-site.example.conf
```

Ajuste `server_name`, caminho do projeto e socket PHP-FPM conforme a VPS.

Permissoes recomendadas para o storage PHP:

```bash
chown -R www-data:www-data /var/www/zapviewer/wwwroot/storage
chmod -R 775 /var/www/zapviewer/wwwroot/storage
```

O exemplo de Nginx usa `client_max_body_size 20M`. Como o upload e feito em chunks de 2 MB e o limite total da aplicacao e 2 GB, ajuste esse valor apenas se mudar o tamanho dos chunks ou a estrategia de upload.

## Seguranca

- Mantenha `storage/` e `python_storage/` fora de qualquer web root publico.
- Uploads aceitos: `.txt` e `.zip`.
- Entradas ZIP com caminhos absolutos, `..`, byte nulo ou drive Windows sao bloqueadas.
- Midias sao servidas por endpoint que valida caminho e pertencimento ao usuario logado.
- Senhas sao armazenadas com hash.
- A versao PHP usa sessao PHP com cookie `HttpOnly` e `SameSite=Lax`.
- A versao Python usa cookie assinado por HMAC; em deploy, defina `ZAPVIEWER_SECRET` fixo.
