import { create } from "zustand";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "good" | "bad";
  icon?: string;
}

interface ToastState {
  toasts: Toast[];
  push: (text: string, tone?: Toast["tone"], icon?: string) => void;
  dismiss: (id: number) => void;
}

let next = 1;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push(text, tone = "info", icon) {
    const id = next++;
    set({ toasts: [...get().toasts.slice(-3), { id, text, tone, icon }] });
    window.setTimeout(() => get().dismiss(id), tone === "bad" ? 4200 : 2800);
  },
  dismiss(id) {
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
}));

export const toast = (text: string, tone?: Toast["tone"], icon?: string) =>
  useToasts.getState().push(text, tone, icon);
