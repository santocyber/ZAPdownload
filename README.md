# WhatsApp Export Viewer

Aplicacao local para importar exportacoes do WhatsApp (`.txt` ou `.zip`), visualizar conversas, pesquisar mensagens e abrir midias anexadas.

O repositorio contem duas implementacoes independentes do mesmo viewer:

- `zapviewer.py`: versao Python monolitica, sem dependencias externas, com servidor HTTP proprio.
- `wwwroot/`: versao PHP + JavaScript para rodar com servidor PHP embutido, Nginx ou PHP-FPM.

As duas versoes usam bancos e storages separados. Dados importados na versao Python nao aparecem automaticamente na versao PHP, e vice-versa.

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

Use a versao Python se quiser rodar tudo com um unico arquivo e sem configurar PHP/Nginx.

Use a versao PHP se quiser deploy em hospedagem ou VPS com PHP-FPM/Nginx.

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

1. No WhatsApp, exporte uma conversa como `.txt` ou `.zip`.
2. Use `.txt` para importar apenas mensagens.
3. Use `.zip` para importar mensagens e midias exportadas.
4. Entre no viewer com seu usuario.
5. Arraste o arquivo para a area de upload ou clique em `Escolher`.
6. Clique em `Enviar`.
7. Aguarde upload, montagem dos chunks e importacao.
8. Abra a conversa na lateral e use busca/filtros conforme necessario.

## Storage E Banco

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

Evite apagar essas pastas se quiser manter usuarios, sessoes, conversas, uploads e midias importadas.

## Estrutura Do Projeto

```text
.
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
