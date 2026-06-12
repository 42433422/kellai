import { create } from 'zustand';
import type { Content, ABTest } from '../types';

interface ContentState {
  draft: Content | null;
  publishQueue: string[];
  activeABTest: ABTest | null;
  setDraft: (c: Content | null) => void;
  addToQueue: (contentId: string) => void;
  setABTest: (test: ABTest | null) => void;
}

export const useContentStore = create<ContentState>((set) => ({
  draft: null,
  publishQueue: [],
  activeABTest: null,
  setDraft: (c) => set({ draft: c }),
  addToQueue: (contentId) =>
    set((s) => ({ publishQueue: [...s.publishQueue, contentId] })),
  setABTest: (test) => set({ activeABTest: test }),
}));
