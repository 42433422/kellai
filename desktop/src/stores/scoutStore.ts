import { create } from 'zustand';
import type { ScoutTarget } from '../types';

interface ScoutState {
  scanKeyword: string;
  highIntentQueue: ScoutTarget[];
  setScanKeyword: (kw: string) => void;
  setHighIntentQueue: (targets: ScoutTarget[]) => void;
}

export const useScoutStore = create<ScoutState>((set) => ({
  scanKeyword: '',
  highIntentQueue: [],
  setScanKeyword: (kw) => set({ scanKeyword: kw }),
  setHighIntentQueue: (targets) => set({ highIntentQueue: targets }),
}));
