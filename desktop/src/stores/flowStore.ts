import { create } from 'zustand';
import type { FlowDefinition, FlowExecution } from '../types';

interface FlowState {
  currentFlow: FlowDefinition | null;
  lastExecution: FlowExecution | null;
  setCurrentFlow: (flow: FlowDefinition | null) => void;
  setLastExecution: (exec: FlowExecution | null) => void;
}

export const useFlowStore = create<FlowState>((set) => ({
  currentFlow: null,
  lastExecution: null,
  setCurrentFlow: (flow) => set({ currentFlow: flow }),
  setLastExecution: (exec) => set({ lastExecution: exec }),
}));
