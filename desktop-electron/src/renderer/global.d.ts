declare global {
  interface Window {
    zapviewer: {
      appInfo(): Promise<{ version: string }>;
      getTheme(): Promise<string>;
      setTheme(theme: string): Promise<string>;
      getStorageInfo(): Promise<Record<string, unknown>>;
      openStorageFolder(): Promise<void>;
      selectImportFile(): Promise<string | null>;
      importFile(filePath: string): Promise<{ chatId: number; title: string; messages: number }>;
      listChats(): Promise<Array<{
        id: number;
        title: string;
        sourceFile: string | null;
        messageCount: number;
        firstMessageAt: string | null;
        lastMessageAt: string | null;
        importedAt: string;
      }>>;
      renameChat(chatId: number, title: string): Promise<{ success: boolean }>;
      deleteChat(chatId: number): Promise<{ success: boolean }>;
      listMessages(chatId: number, options?: { limit?: number; offset?: number }): Promise<Array<{
        id: number;
        chatId: number;
        sender: string | null;
        body: string;
        sentAt: string | null;
        mediaPath: string | null;
      }>>;
      searchMessages(query: string, options?: { chatId?: number; limit?: number; offset?: number }): Promise<Array<{
        id: number;
        chatId: number;
        chatTitle?: string;
        sender: string | null;
        body: string;
        sentAt: string | null;
        mediaPath: string | null;
      }>>;
      openMedia(mediaPath: string): Promise<{ success: boolean }>;
    };
  }
}

export {};
