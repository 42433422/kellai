import { create } from "zustand";

interface AdvancedPanelState {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const useAdvancedPanelStore = create<AdvancedPanelState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set((state) => ({ open: !state.open })),
}));

export default useAdvancedPanelStore;
