import { create } from 'zustand';

const ALERTS_KEY = 'kellai:finance:alertsRead';

interface FinanceState {
  readAlertIds: string[];
  markAlertRead: (id: string) => void;
  loadFromStorage: () => void;
}

export const useFinanceStore = create<FinanceState>((set, get) => ({
  readAlertIds: [],

  markAlertRead: (id) => {
    const ids = [...new Set([...get().readAlertIds, id])];
    localStorage.setItem(ALERTS_KEY, JSON.stringify(ids));
    set({ readAlertIds: ids });
  },

  loadFromStorage: () => {
    try {
      const raw = localStorage.getItem(ALERTS_KEY);
      set({ readAlertIds: raw ? JSON.parse(raw) : [] });
    } catch {
      set({ readAlertIds: [] });
    }
  },
}));
