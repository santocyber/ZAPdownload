import "./styles.css";

type Chat = {
  id: number;
  title: string;
  sourceFile: string | null;
  messageCount: number;
  firstMessageAt: string | null;
  lastMessageAt: string | null;
  importedAt: string;
};

type Message = {
  id: number;
  chatId: number;
  sender: string | null;
  body: string;
  sentAt: string | null;
  mediaPath: string | null;
};

const state = {
  chats: [] as Chat[],
  activeChat: null as Chat | null,
  messages: [] as Message[],
  theme: "system",
  loading: false,
};

const app = document.querySelector<HTMLDivElement>("#app")!;

function formatDate(value: string | null): string {
  if (!value) return "Sem data";
  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function applyTheme(theme: string): void {
  state.theme = theme;
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = theme === "system" ? (systemDark ? "dark" : "light") : theme;
}

async function boot(): Promise<void> {
  applyTheme(await window.zapviewer.getTheme());
  await refreshChats();
  render();
}

async function refreshChats(): Promise<void> {
  state.chats = await window.zapviewer.listChats();
  if (!state.activeChat && state.chats[0]) await openChat(state.chats[0].id, false);
}

async function openChat(chatId: number, shouldRender = true): Promise<void> {
  state.activeChat = state.chats.find((chat) => chat.id === chatId) ?? null;
  state.messages = state.activeChat ? await window.zapviewer.listMessages(chatId, { limit: 800, offset: 0 }) : [];
  if (shouldRender) render();
}

async function importConversation(): Promise<void> {
  const file = await window.zapviewer.selectImportFile();
  if (!file) return;
  state.loading = true;
  render();
  try {
    const result = await window.zapviewer.importFile(file);
    await refreshChats();
    await openChat(result.chatId, false);
  } catch (error) {
    alert(error instanceof Error ? error.message : String(error));
  } finally {
    state.loading = false;
    render();
  }
}

async function search(query: string): Promise<void> {
  if (!query.trim()) {
    if (state.activeChat) state.messages = await window.zapviewer.listMessages(state.activeChat.id, { limit: 800 });
  } else {
    state.messages = await window.zapviewer.searchMessages(query, { chatId: state.activeChat?.id, limit: 500 });
  }
  render();
}

async function cycleTheme(): Promise<void> {
  const next = state.theme === "system" ? "dark" : state.theme === "dark" ? "light" : "system";
  applyTheme(await window.zapviewer.setTheme(next));
  render();
}

function render(): void {
  app.innerHTML = `
    <main class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="logo">Z</div>
          <div>
            <h1>ZapViewer</h1>
            <p>Leitor local de conversas</p>
          </div>
        </div>
        <button class="import-card" id="importButton" ${state.loading ? "disabled" : ""}>
          <span>${state.loading ? "Importando..." : "Importar .txt ou .zip"}</span>
          <small>WhatsApp export offline</small>
        </button>
        <div class="section-title">Conversas</div>
        <div class="chat-list">
          ${state.chats.length ? state.chats.map(renderChatButton).join("") : `<div class="empty-list">Nenhuma conversa importada ainda.</div>`}
        </div>
      </aside>
      <section class="workspace">
        <header class="topbar">
          <div>
            <p class="eyebrow">${state.activeChat ? `${state.activeChat.messageCount} mensagens` : "Pronto para importar"}</p>
            <h2>${escapeHtml(state.activeChat?.title ?? "Sua biblioteca local")}</h2>
          </div>
          <div class="top-actions">
            <input id="searchInput" class="search" placeholder="Buscar nesta conversa..." ${state.activeChat ? "" : "disabled"} />
            <button id="themeButton" class="ghost">Tema: ${escapeHtml(state.theme)}</button>
          </div>
        </header>
        <div class="content">
          <div class="timeline">
            ${state.activeChat ? renderMessages() : renderEmptyState()}
          </div>
          <aside class="details">
            <h3>Detalhes</h3>
            ${renderDetails()}
          </aside>
        </div>
      </section>
    </main>
  `;

  document.querySelector<HTMLButtonElement>("#importButton")?.addEventListener("click", importConversation);
  document.querySelector<HTMLButtonElement>("#themeButton")?.addEventListener("click", cycleTheme);
  document.querySelector<HTMLInputElement>("#searchInput")?.addEventListener("input", (event) => {
    const input = event.currentTarget as HTMLInputElement | null;
    if (!input) return;
    window.setTimeout(() => search(input.value), 120);
  });
  document.querySelectorAll<HTMLButtonElement>("[data-chat]").forEach((button) => {
    button.addEventListener("click", () => openChat(Number(button.dataset.chat)));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-media]").forEach((button) => {
    button.addEventListener("click", () => window.zapviewer.openMedia(button.dataset.media ?? ""));
  });
}

function renderChatButton(chat: Chat): string {
  const active = state.activeChat?.id === chat.id ? "active" : "";
  return `
    <button class="chat-item ${active}" data-chat="${chat.id}">
      <strong>${escapeHtml(chat.title)}</strong>
      <span>${chat.messageCount} mensagens</span>
      <small>${formatDate(chat.lastMessageAt)}</small>
    </button>
  `;
}

function renderMessages(): string {
  if (!state.messages.length) return `<div class="empty-state"><h3>Nada encontrado</h3><p>Tente outra busca.</p></div>`;
  return state.messages.map((message) => `
    <article class="message">
      <div class="message-meta">
        <strong>${escapeHtml(message.sender ?? "Sistema")}</strong>
        <time>${formatDate(message.sentAt)}</time>
      </div>
      <p>${escapeHtml(message.body).replaceAll("\n", "<br>")}</p>
      ${message.mediaPath ? `<button class="media-chip" data-media="${escapeHtml(message.mediaPath)}">Abrir mídia</button>` : ""}
    </article>
  `).join("");
}

function renderEmptyState(): string {
  return `
    <div class="empty-state hero">
      <span class="spark">TXT + ZIP</span>
      <h3>Importe uma conversa do WhatsApp</h3>
      <p>O app salva tudo localmente no seu computador, sem login e sem serviços externos.</p>
      <button id="importButtonHero" onclick="document.getElementById('importButton')?.click()">Começar importação</button>
    </div>
  `;
}

function renderDetails(): string {
  if (!state.activeChat) {
    return `<p>Escolha uma conversa ou importe um arquivo para ver os detalhes.</p>`;
  }
  return `
    <dl>
      <dt>Arquivo</dt><dd>${escapeHtml(state.activeChat.sourceFile ?? "-")}</dd>
      <dt>Primeira mensagem</dt><dd>${formatDate(state.activeChat.firstMessageAt)}</dd>
      <dt>Última mensagem</dt><dd>${formatDate(state.activeChat.lastMessageAt)}</dd>
      <dt>Importada em</dt><dd>${formatDate(state.activeChat.importedAt)}</dd>
    </dl>
  `;
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state.theme === "system") applyTheme("system");
});

void boot();
