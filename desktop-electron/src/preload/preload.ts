import { contextBridge, ipcRenderer } from "electron";

const api = {
  appInfo: () => ipcRenderer.invoke("app:info"),
  getTheme: () => ipcRenderer.invoke("settings:get-theme"),
  setTheme: (theme: string) => ipcRenderer.invoke("settings:set-theme", theme),
  getStorageInfo: () => ipcRenderer.invoke("storage:info"),
  openStorageFolder: () => ipcRenderer.invoke("storage:open"),
  selectImportFile: () => ipcRenderer.invoke("import:select-file"),
  importFile: (filePath: string) => ipcRenderer.invoke("import:file", filePath),
  listChats: () => ipcRenderer.invoke("chats:list"),
  renameChat: (chatId: number, title: string) => ipcRenderer.invoke("chats:rename", chatId, title),
  deleteChat: (chatId: number) => ipcRenderer.invoke("chats:delete", chatId),
  listMessages: (chatId: number, options?: { limit?: number; offset?: number }) => ipcRenderer.invoke("messages:list", chatId, options),
  searchMessages: (query: string, options?: { chatId?: number; limit?: number; offset?: number }) => ipcRenderer.invoke("messages:search", query, options),
  openMedia: (mediaPath: string) => ipcRenderer.invoke("media:open", mediaPath),
};

contextBridge.exposeInMainWorld("zapviewer", api);

export type ZapViewerApi = typeof api;
