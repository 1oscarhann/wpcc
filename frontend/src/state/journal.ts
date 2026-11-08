// Phase 16: the journal — quests, achievements and titles, the skill tree, the login calendar.
import { create } from "zustand";
import { api } from "../api/client";

export interface QuestView {
  key: string;
  title: string;
  progress: number;
  target: number;
  done: boolean;
  claimed: boolean;
  reward: { xp: number; coins: [number, number]; token: number };
}

export interface MainQuestView {
  key: string;
  index: number;
  total: number;
  title: string;
  progress: number;
  target: number;
  done: boolean;
  reward: { xp: number; coins: number; title: string | null };
}

export interface QuestsView {
  daily: QuestView[];
  weekly: QuestView[];
  main: MainQuestView | null;
  resets: { daily_ms: number; weekly_ms: number };
}

export interface AchievementView {
  key: string;
  name: string;
  desc: string;
  progress: number;
  target: number;
  unlocked: boolean;
  claimed: boolean;
  title: string | null;
  coins: number;
}

export interface SkillsView {
  level: number;
  points: number;
  spent: number;
  ranks: Record<string, number>;
  respec_cost: number;
  perks: Record<string, number>;
  /** null = you can learn it now; otherwise why not */
  can: Record<string, null | "unknown_skill" | "maxed" | "no_points" | "locked">;
}

export interface CalendarDay {
  coins: number;
  res: Record<string, number>;
  items: Record<string, number>;
  title: string | null;
}

export interface CalendarView {
  day: number;
  round: number;
  claimed_today: boolean;
  days: CalendarDay[];
}

export interface JournalView {
  quests: QuestsView;
  achievements: { achievements: AchievementView[]; titles: string[]; title: string | null };
  skills: SkillsView;
  calendar: CalendarView;
}

export type JournalTab = "quests" | "skills" | "achievements" | "pets" | "trophies" | "collection" | "calendar";

interface JournalStore {
  tab: JournalTab | null; // null = closed
  view: JournalView | null;
  set: (p: Partial<JournalStore>) => void;
  fetch: () => Promise<JournalView | null>;
}

let inflight: Promise<JournalView | null> | null = null;

export const useJournal = create<JournalStore>((set) => ({
  tab: null,
  view: null,
  set: (p) => set(p),
  fetch: () => {
    if (inflight) return inflight;
    inflight = api<JournalView>("/api/journal")
      .then((v) => {
        set({ view: v });
        return v;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
    return inflight;
  },
}));

/** Things to collect, per tab. The HUD button shows the total as a dot. */
export function journalDots(v: JournalView | null): Record<JournalTab, number> {
  const out: Record<JournalTab, number> = { quests: 0, skills: 0, achievements: 0, pets: 0, trophies: 0, collection: 0, calendar: 0 };
  if (!v) return out;
  const ready = (q: { done: boolean; claimed: boolean }) => q.done && !q.claimed;
  out.quests = v.quests.daily.filter(ready).length + v.quests.weekly.filter(ready).length + (v.quests.main?.done ? 1 : 0);
  out.achievements = v.achievements.achievements.filter((a) => a.unlocked && !a.claimed).length;
  out.skills = Math.max(0, v.skills.points - v.skills.spent) > 0 ? 1 : 0;
  out.calendar = v.calendar.claimed_today ? 0 : 1;
  return out;
}
