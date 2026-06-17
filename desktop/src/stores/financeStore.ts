import { create } from 'zustand';

const ALERTS_KEY = 'kellai:finance:alertsRead';

interface FinanceState {
  readAlertIds: string[];
  markAlertRead: (id: string) => void;
  markAllAlertsRead: (ids: string[]) => void;
  loadFromStorage: () => void;
}

export const useFinanceStore = create<FinanceState>((set, get) => ({
  readAlertIds: [],

  markAlertRead: (id) => {
    const ids = [...new Set([...get().readAlertIds, id])];
    localStorage.setItem(ALERTS_KEY, JSON.stringify(ids));
    set({ readAlertIds: ids });
  },

  markAllAlertsRead: (ids) => {
    const merged = [...new Set([...get().readAlertIds, ...ids])];
    localStorage.setItem(ALERTS_KEY, JSON.stringify(merged));
    set({ readAlertIds: merged });
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
