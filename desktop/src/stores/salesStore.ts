import { create } from 'zustand';
import type { SalesFlow, Quote, PerformanceGoal } from '../types';

const GOALS_KEY = 'kellai:sales:goals';
const HINTS_KEY = 'kellai:sales:scriptHints';

interface SalesState {
  activeFlowId: string | null;
  currentStep: string;
  activeQuote: Quote | null;
  performanceGoals: PerformanceGoal[];
  scriptHintsEnabled: boolean;
  selectedCustomerId: number | null;
  setActiveFlow: (flow: SalesFlow | null) => void;
  setActiveQuote: (quote: Quote | null) => void;
  setSelectedCustomer: (id: number | null) => void;
  setGoal: (goal: PerformanceGoal) => void;
  toggleScriptHints: () => void;
  loadFromStorage: () => void;
}

function loadGoals(): PerformanceGoal[] {
  try {
    const raw = localStorage.getItem(GOALS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export const useSalesStore = create<SalesState>((set, get) => ({
  activeFlowId: null,
  currentStep: 'requirement',
  activeQuote: null,
  performanceGoals: [],
  scriptHintsEnabled: true,
  selectedCustomerId: null,

  setActiveFlow: (flow) =>
    set({
      activeFlowId: flow?.id ?? null,
      currentStep: flow?.current_step ?? 'requirement',
    }),

  setActiveQuote: (quote) => set({ activeQuote: quote }),

  setSelectedCustomer: (id) => set({ selectedCustomerId: id }),

  setGoal: (goal) => {
    const goals = [...get().performanceGoals.filter((g) => g.id !== goal.id), goal];
    localStorage.setItem(GOALS_KEY, JSON.stringify(goals));
    set({ performanceGoals: goals });
  },

  toggleScriptHints: () => {
    const next = !get().scriptHintsEnabled;
    localStorage.setItem(HINTS_KEY, next ? '1' : '0');
    set({ scriptHintsEnabled: next });
  },

  loadFromStorage: () => {
    const hints = localStorage.getItem(HINTS_KEY);
    set({
      performanceGoals: loadGoals(),
      scriptHintsEnabled: hints !== '0',
    });
  },
}));
