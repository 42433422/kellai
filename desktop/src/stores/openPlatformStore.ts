import { create } from 'zustand';

const WEBHOOK_KEY = 'kellai:open:webhooks';

interface OpenPlatformState {
  apiKeyCount: number;
  webhookUrls: string[];
  setApiKeyCount: (n: number) => void;
  addWebhook: (url: string) => void;
  loadFromStorage: () => void;
}

export const useOpenPlatformStore = create<OpenPlatformState>((set, get) => ({
  apiKeyCount: 0,
  webhookUrls: [],

  setApiKeyCount: (n) => set({ apiKeyCount: n }),

  addWebhook: (url) => {
    const urls = [...get().webhookUrls, url];
    localStorage.setItem(WEBHOOK_KEY, JSON.stringify(urls));
    set({ webhookUrls: urls });
  },

  loadFromStorage: () => {
    try {
      const raw = localStorage.getItem(WEBHOOK_KEY);
      set({ webhookUrls: raw ? JSON.parse(raw) : [] });
    } catch {
      set({ webhookUrls: [] });
    }
  },
}));
