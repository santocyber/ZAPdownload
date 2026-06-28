const state = {
  conversations: [],
  activeConversationId: null,
  selectedFile: null,
  timers: {
    globalSearch: null,
    chatSearch: null,
    loadMore: null,
  },
  requests: {
    conversations: 0,
    messages: 0,
    globalSearch: 0,
    chatSearch: 0,
  },
  messagesOffset: 0,
  allMessages: [],
  allMessagesLoaded: false,
  loadingMore: false,
};

const elements = {
  dropArea: document.getElementById("dropArea"),
  browseButton: document.getElementById("browseButton"),
  startUpload: document.getElementById("startUpload"),
  pauseUpload: document.getElementById("pauseUpload"),
  progressBar: document.getElementById("progressBar"),
  progressText: document.getElementById("progressText"),
  refreshButton: document.getElementById("refreshButton"),
  globalSearchInput: document.getElementById("globalSearchInput"),
  globalDateStart: document.getElementById("globalDateStart"),
  globalDateEnd: document.getElementById("globalDateEnd"),
  clearGlobalSearch: document.getElementById("clearGlobalSearch"),
  chatSearchInput: document.getElementById("chatSearchInput"),
  chatDateStart: document.getElementById("chatDateStart"),
  chatDateEnd: document.getElementById("chatDateEnd"),
  clearChatSearch: document.getElementById("clearChatSearch"),
  conversationList: document.getElementById("conversationList"),
  messages: document.getElementById("messages"),
  chatTitle: document.getElementById("chatTitle"),
  chatSubtitle: document.getElementById("chatSubtitle"),
  messageCount: document.getElementById("messageCount"),
};

const uploader = window.Resumable
  ? new Resumable({
      target: "upload-chunk.php",
      testTarget: "upload-chunk.php",
      chunkSize: 2 * 1024 * 1024,
      forceChunkSize: true,
      simultaneousUploads: 2,
      testChunks: true,
      fileParameterName: "file",
      fileType: ["txt", "zip"],
      maxFileSize: 2 * 1024 * 1024 * 1024,
      maxChunkRetries: 5,
      chunkRetryInterval: 1000,
    })
  : null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatDate(value) {
  if (!value) return "";
  const normalized = value.replace(" ", "T");
  const date = new Date(normalized);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function shortText(value, limit = 80) {
  const text = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function setProgress(percent, text) {
  elements.progressBar.value = percent;
  elements.progressText.textContent = text;
}

function showError(message) {
  elements.progressText.textContent = message;
  elements.progressText.classList.add("error");
  setTimeout(() => elements.progressText.classList.remove("error"), 3500);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let data;

  try {
    data = await response.json();
  } catch (error) {
    throw new Error("Resposta invalida do servidor.");
  }

  if (!response.ok || !data.success) {
    throw new Error(data.error || "Falha na requisicao.");
  }

  return data;
}

function setupUploader() {
  if (!uploader || !uploader.support) {
    setProgress(0, "Seu navegador nao suporta upload resumivel.");
    elements.browseButton.classList.add("disabled");
    return;
  }

  uploader.assignBrowse(elements.browseButton);
  uploader.assignDrop(elements.dropArea);

  uploader.on("fileAdded", (file) => {
    uploader.files
      .filter((item) => item.uniqueIdentifier !== file.uniqueIdentifier)
      .forEach((item) => uploader.removeFile(item));

    state.selectedFile = file;
    elements.startUpload.disabled = false;
    elements.pauseUpload.disabled = true;
    setProgress(0, `Selecionado: ${file.fileName}`);
  });

  uploader.on("fileProgress", (file) => {
    const percent = Math.floor(file.progress() * 100);
    setProgress(percent, `Enviando ${file.fileName}: ${percent}%`);
  });

  uploader.on("fileRetry", (file) => {
    setProgress(
      Math.floor(file.progress() * 100),
      `Conexao instavel. Retentando ${file.fileName}...`,
    );
  });

  uploader.on("uploadStart", () => {
    elements.startUpload.disabled = true;
    elements.pauseUpload.disabled = false;
  });

  uploader.on("pause", () => {
    elements.startUpload.disabled = false;
    elements.pauseUpload.disabled = true;
    setProgress(Math.floor(uploader.progress() * 100), "Upload pausado.");
  });

  uploader.on("fileSuccess", async (file, response) => {
    let payload;

    try {
      payload = JSON.parse(response);
    } catch (error) {
      showError(`Resposta invalida do servidor: ${response}`);
      return;
    }

    if (!payload.success || !payload.file) {
      showError(
        payload.error ||
          "Upload concluido, mas o arquivo final nao foi informado.",
      );
      return;
    }

    setProgress(100, "Upload concluido. Importando mensagens...");
    await importUploadedFile(payload.file);
  });

  uploader.on("fileError", (file, message) => {
    elements.startUpload.disabled = false;
    elements.pauseUpload.disabled = true;
    showError(`Erro no upload de ${file.fileName}: ${message}`);
  });
}

async function importUploadedFile(file) {
  try {
    const data = await fetchJson("import.php", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ file }),
    });

    const conversation = data.conversation;
    setProgress(100, `Importado: ${conversation.messages} mensagens.`);
    uploader.cancel();
    state.selectedFile = null;
    elements.startUpload.disabled = true;
    elements.pauseUpload.disabled = true;

    await loadConversations();
    await openConversation(conversation.conversation_id);
  } catch (error) {
    showError(error.message);
  }
}

async function loadConversations() {
  const requestId = ++state.requests.conversations;

  try {
    const data = await fetchJson("api.php?action=conversations");

    if (requestId !== state.requests.conversations) return;

    state.conversations = data.conversations;

    if (
      state.activeConversationId &&
      !state.conversations.some(
        (item) => Number(item.id) === Number(state.activeConversationId),
      )
    ) {
      setWelcomeState();
    }

    renderConversations();
  } catch (error) {
    showError(error.message || "Nao foi possivel carregar conversas.");
  }
}

function renderConversations() {
  if (state.conversations.length === 0) {
    elements.conversationList.innerHTML =
      '<div class="muted-card">Nenhuma conversa importada ainda.</div>';
    return;
  }

  elements.conversationList.innerHTML = state.conversations
    .map((conversation) => {
      const active =
        Number(conversation.id) === Number(state.activeConversationId);

      return `
        <div class="conversation-row ${active ? "active" : ""}">
          <button class="conversation-item" data-open-id="${conversation.id}" type="button">
            <span class="avatar">${escapeHtml(conversation.title.slice(0, 1).toUpperCase())}</span>
            <span class="conversation-text">
              <strong>${escapeHtml(conversation.title)}</strong>
              <small>${escapeHtml(shortText(conversation.last_message || "Sem mensagens"))}</small>
            </span>
            <span class="conversation-meta">
              <time>${escapeHtml(formatDate(conversation.last_date))}</time>
              <b>${conversation.message_count}</b>
            </span>
          </button>
          <button class="delete-conversation" data-delete-id="${conversation.id}" type="button" title="Apagar conversa">X</button>
        </div>
      `;
    })
    .join("");
}

async function openConversation(conversationId, options = {}) {
  state.activeConversationId = Number(conversationId);
  state.requests.globalSearch++;

  if (options.clearGlobal !== false) {
    clearGlobalFilters(false);
  }

  if (options.clearChat !== false) {
    clearChatFilters(false);
  }

  setChatControlsEnabled(true);
  renderConversations();

  const conversation = findConversation(state.activeConversationId);
  elements.chatTitle.textContent = conversation?.title || "Conversa";
  elements.chatSubtitle.textContent = "Mensagens importadas";
  elements.messageCount.textContent = conversation
    ? `${conversation.message_count} mensagens`
    : "";

  await loadMessages(state.activeConversationId);
}

async function loadMessages(conversationId) {
  const requestId = ++state.requests.messages;
  state.messagesOffset = 0;
  state.allMessages = [];
  state.allMessagesLoaded = false;
  state.loadingMore = false;

  elements.messages.classList.remove("empty-state");
  elements.messages.innerHTML =
    '<div class="loading">Carregando mensagens...</div>';

  try {
    const data = await fetchJson(
      `api.php?action=messages&conversation_id=${conversationId}&limit=2000&offset=0`,
    );

    if (requestId !== state.requests.messages) return;

    state.allMessages = data.messages;
    state.messagesOffset = state.allMessages.length;
    state.allMessagesLoaded = data.messages.length < 2000;

    renderMessages(state.allMessages);
  } catch (error) {
    showError(error.message || "Nao foi possivel carregar mensagens.");
  }
}

async function loadMoreMessages() {
  if (state.loadingMore || state.allMessagesLoaded || !state.activeConversationId) return;

  state.loadingMore = true;

  try {
    const data = await fetchJson(
      `api.php?action=messages&conversation_id=${state.activeConversationId}&limit=2000&offset=${state.messagesOffset}`,
    );

    if (data.messages.length === 0) {
      state.allMessagesLoaded = true;
      state.loadingMore = false;
      renderMessages(state.allMessages);
      return;
    }

    state.allMessages = [...state.allMessages, ...data.messages];
    state.messagesOffset += data.messages.length;
    state.allMessagesLoaded = data.messages.length < 2000;

    state.loadingMore = false;
    renderMessages(state.allMessages);
  } catch (error) {
    showError(error.message || "Erro ao carregar mais mensagens.");
  } finally {
    state.loadingMore = false;
  }
}

function renderMessages(messages, options = {}) {
  const isSearch = Boolean(options.isSearch);
  const isGlobalSearch = Boolean(options.global);
  const query = options.query || "";

  if (messages.length === 0) {
    elements.messages.innerHTML =
      '<div class="empty-results">Nenhuma mensagem encontrada.</div>';
    return;
  }

  let html = messages
    .map((message) => {
      const mine = ["voce", "you"].includes(
        String(message.sender || "").toLowerCase(),
      );
      const body = query
        ? highlightBody(message.body, query)
        : escapeHtml(message.body).replaceAll("\n", "<br>");
      const media = renderMedia(message);

      return `
        <article class="message ${mine ? "mine" : ""}" data-conversation-id="${message.conversation_id}">
          ${isSearch && isGlobalSearch ? `<button class="jump-conversation" data-open-id="${message.conversation_id}" type="button">${escapeHtml(message.conversation_title || "Conversa")}</button>` : ""}
          ${message.sender ? `<strong>${escapeHtml(message.sender)}</strong>` : ""}
          <div class="message-body">${body}</div>
          ${media}
          <time>${escapeHtml(formatDate(message.sent_at))}</time>
        </article>
      `;
    })
    .join("");

  if (!isSearch && !state.allMessagesLoaded) {
    html =
      html +
      `<button class="load-more-btn" type="button" ${state.loadingMore ? "disabled" : ""}>
        ${state.loadingMore ? "Carregando..." : "Carregar mensagens mais antigas"}
      </button>`;
  }

  elements.messages.innerHTML = html;

  if (!isSearch) {
    elements.messages.scrollTop = 0;
  }
}

function highlightBody(body, query) {
  const text = String(body ?? "");
  const terms = query
    .trim()
    .split(/\s+/)
    .filter((term) => term.length >= 2)
    .slice(0, 8)
    .map(escapeRegExp);

  if (terms.length === 0) {
    return escapeHtml(text).replaceAll("\n", "<br>");
  }

  const source = terms.join("|");
  const splitRegex = new RegExp(`(${source})`, "gi");
  const matchRegex = new RegExp(`^(?:${source})$`, "i");

  return text
    .split(splitRegex)
    .map((part) =>
      matchRegex.test(part)
        ? `<mark>${escapeHtml(part)}</mark>`
        : escapeHtml(part),
    )
    .join("")
    .replaceAll("\n", "<br>");
}

function renderMedia(message) {
  if (!message.media_url) return "";

  const path = String(message.media_path || "").toLowerCase();
  const url = message.media_url;

  if (/\.(jpg|jpeg|png|gif|webp)$/.test(path)) {
    return `<a class="media-preview" href="${url}" target="_blank" rel="noreferrer"><img src="${url}" alt="Midia anexada"></a>`;
  }

  if (/\.(mp4|mov|m4v|3gp)$/.test(path)) {
    return `<video class="media-video" src="${url}" controls></video>`;
  }

  if (/\.(mp3|m4a|opus|ogg|wav)$/.test(path)) {
    return `<audio class="media-audio" src="${url}" controls></audio>`;
  }

  return `<a class="attachment" href="${url}" target="_blank" rel="noreferrer">Abrir anexo</a>`;
}

function getGlobalFilters() {
  return {
    query: elements.globalSearchInput.value.trim(),
    dateStart: elements.globalDateStart.value,
    dateEnd: elements.globalDateEnd.value,
  };
}

function getChatFilters() {
  return {
    query: elements.chatSearchInput.value.trim(),
    dateStart: elements.chatDateStart.value,
    dateEnd: elements.chatDateEnd.value,
  };
}

function hasFilters(filters) {
  return (
    filters.query.length >= 2 || Boolean(filters.dateStart || filters.dateEnd)
  );
}

function buildSearchUrl(filters, options = {}) {
  const params = new URLSearchParams({
    action: "search",
    q: filters.query,
    limit: options.limit || "120",
    sort: options.sort || "desc",
  });

  if (filters.dateStart) params.set("date_start", filters.dateStart);
  if (filters.dateEnd) params.set("date_end", filters.dateEnd);
  if (options.conversationId) {
    params.set("conversation_id", String(options.conversationId));
  }

  return `api.php?${params.toString()}`;
}

function scheduleGlobalSearch() {
  clearTimeout(state.timers.globalSearch);
  state.timers.globalSearch = setTimeout(runGlobalSearch, 250);
}

async function runGlobalSearch() {
  const filters = getGlobalFilters();

  if (!hasFilters(filters)) {
    state.requests.globalSearch++;

    if (state.activeConversationId) {
      await loadMessages(state.activeConversationId);
    } else {
      setWelcomeState();
    }

    return;
  }

  const requestId = ++state.requests.globalSearch;
  state.activeConversationId = null;
  state.requests.messages++;
  setChatControlsEnabled(false);
  renderConversations();

  elements.chatTitle.textContent = filters.query
    ? `Busca geral: ${filters.query}`
    : "Filtro geral por data";
  elements.chatSubtitle.textContent = describeFilter(
    filters,
    "Todas as conversas",
  );
  elements.messageCount.textContent = "Buscando...";
  elements.messages.classList.remove("empty-state");
  elements.messages.innerHTML =
    '<div class="loading">Buscando mensagens...</div>';

  try {
    const data = await fetchJson(buildSearchUrl(filters));

    if (requestId !== state.requests.globalSearch) return;

    elements.messageCount.textContent = `${data.messages.length} resultados`;
    renderMessages(data.messages, {
      isSearch: true,
      global: true,
      query: filters.query,
    });
  } catch (error) {
    if (requestId === state.requests.globalSearch) {
      showError(error.message || "Busca falhou.");
    }
  }
}

function scheduleChatSearch() {
  clearTimeout(state.timers.chatSearch);
  state.timers.chatSearch = setTimeout(runChatSearch, 250);
}

async function runChatSearch() {
  if (!state.activeConversationId) return;

  const filters = getChatFilters();
  const conversation = findConversation(state.activeConversationId);

  if (!hasFilters(filters)) {
    elements.chatSubtitle.textContent = "Mensagens importadas";
    elements.messageCount.textContent = conversation
      ? `${conversation.message_count} mensagens`
      : "";
    await loadMessages(state.activeConversationId);
    return;
  }

  const requestId = ++state.requests.chatSearch;
  state.requests.messages++;
  elements.chatTitle.textContent = conversation?.title || "Conversa";
  elements.chatSubtitle.textContent = describeFilter(
    filters,
    "Resultados neste chat",
  );
  elements.messageCount.textContent = "Buscando...";
  elements.messages.classList.remove("empty-state");
  elements.messages.innerHTML =
    '<div class="loading">Buscando neste chat...</div>';

  try {
    const data = await fetchJson(
      buildSearchUrl(filters, {
        conversationId: state.activeConversationId,
        limit: "300",
        sort: "asc",
      }),
    );

    if (requestId !== state.requests.chatSearch) return;

    elements.messageCount.textContent = `${data.messages.length} resultados`;
    renderMessages(data.messages, {
      isSearch: true,
      global: false,
      query: filters.query,
    });
  } catch (error) {
    if (requestId === state.requests.chatSearch) {
      showError(error.message || "Busca no chat falhou.");
    }
  }
}

function describeFilter(filters, fallback) {
  const parts = [];

  if (filters.dateStart) parts.push(`de ${filters.dateStart}`);
  if (filters.dateEnd) parts.push(`ate ${filters.dateEnd}`);

  return parts.length > 0 ? `${fallback} (${parts.join(" ")})` : fallback;
}

function clearGlobalFilters(runSearch = true) {
  elements.globalSearchInput.value = "";
  elements.globalDateStart.value = "";
  elements.globalDateEnd.value = "";

  if (runSearch) {
    runGlobalSearch();
  }
}

function clearChatFilters(runSearch = true) {
  elements.chatSearchInput.value = "";
  elements.chatDateStart.value = "";
  elements.chatDateEnd.value = "";

  if (runSearch) {
    runChatSearch();
  }
}

function setChatControlsEnabled(enabled) {
  elements.chatSearchInput.disabled = !enabled;
  elements.chatDateStart.disabled = !enabled;
  elements.chatDateEnd.disabled = !enabled;
  elements.clearChatSearch.disabled = !enabled;

  if (!enabled) {
    clearChatFilters(false);
  }
}

function setWelcomeState() {
  state.activeConversationId = null;
  setChatControlsEnabled(false);
  renderConversations();
  elements.chatSubtitle.textContent = "Selecione uma conversa";
  elements.chatTitle.textContent = "WhatsApp Export Viewer";
  elements.messageCount.textContent = "";
  elements.messages.className = "messages empty-state";
  elements.messages.innerHTML = `
    <div>
      <h3>Importe uma exportacao do WhatsApp</h3>
      <p>Use .txt para conversas simples ou .zip para incluir midias exportadas.</p>
    </div>
  `;
}

function findConversation(conversationId) {
  return state.conversations.find(
    (item) => Number(item.id) === Number(conversationId),
  );
}

async function deleteConversation(conversationId) {
  const conversation = findConversation(conversationId);
  const title = conversation?.title || "esta conversa";

  if (
    !window.confirm(
      `Apagar ${title}? Voce podera importar uma exportacao atualizada depois.`,
    )
  ) {
    return;
  }

  try {
    await fetchJson("api.php?action=delete_conversation", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ conversation_id: conversationId }),
    });

    const deletedActive =
      Number(state.activeConversationId) === Number(conversationId);
    setProgress(0, "Conversa apagada. Voce pode importar a versao atualizada.");
    await loadConversations();

    if (deletedActive) {
      setWelcomeState();
    }

    if (hasFilters(getGlobalFilters())) {
      runGlobalSearch();
    }
  } catch (error) {
    showError(error.message || "Nao foi possivel apagar a conversa.");
  }
}

elements.startUpload.addEventListener("click", () => {
  if (uploader && state.selectedFile) {
    uploader.upload();
  }
});

elements.pauseUpload.addEventListener("click", () => {
  if (uploader && uploader.isUploading()) {
    uploader.pause();
  }
});

elements.refreshButton.addEventListener("click", loadConversations);
elements.clearGlobalSearch.addEventListener("click", () =>
  clearGlobalFilters(true),
);
elements.clearChatSearch.addEventListener("click", () =>
  clearChatFilters(true),
);

elements.conversationList.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-id]");

  if (deleteButton) {
    event.preventDefault();
    event.stopPropagation();
    deleteConversation(deleteButton.dataset.deleteId);
    return;
  }

  const openButton = event.target.closest("[data-open-id]");

  if (openButton) {
    openConversation(openButton.dataset.openId);
  }
});

elements.messages.addEventListener("click", (event) => {
  const loadMoreBtn = event.target.closest(".load-more-btn");

  if (loadMoreBtn) {
    loadMoreMessages();
    return;
  }

  const item = event.target.closest(".jump-conversation");

  if (item) {
    openConversation(item.dataset.openId);
  }
});

[
  elements.globalSearchInput,
  elements.globalDateStart,
  elements.globalDateEnd,
].forEach((input) => {
  input.addEventListener("input", scheduleGlobalSearch);
  input.addEventListener("change", scheduleGlobalSearch);
});

[
  elements.chatSearchInput,
  elements.chatDateStart,
  elements.chatDateEnd,
].forEach((input) => {
  input.addEventListener("input", scheduleChatSearch);
  input.addEventListener("change", scheduleChatSearch);
});

setupUploader();
setChatControlsEnabled(false);
loadConversations();
