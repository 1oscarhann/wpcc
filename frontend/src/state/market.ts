// Phase 7 UI state: the market panel, the wandering merchant's cart, and whether you're standing at it.
import { create } from "zustand";
import { api } from "../api/client";
import type { MerchantView } from "../api/types";

interface MarketStore {
  marketOpen: boolean;
  merchantOpen: boolean;
  merchant: MerchantView | null;
  near: boolean; // client-side: the local avatar is within reach of the cart
  set: (p: Partial<MarketStore>) => void;
  fetchMerchant: () => Promise<MerchantView | null>;
}

let inflight: Promise<MerchantView | null> | null = null;

export const useMarket = create<MarketStore>((set) => ({
  marketOpen: false,
  merchantOpen: false,
  merchant: null,
  near: false,
  set: (p) => set(p),
  fetchMerchant: () => {
    if (inflight) return inflight;
    inflight = api<MerchantView>("/api/merchant/hub")
      .then((m) => {
        set({ merchant: m });
        return m;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
    return inflight;
  },
}));
