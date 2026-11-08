// Phase 16: the journal. Quests (daily, weekly, the main story), the skill tree, achievements and
// titles, the collection book and the 28-day login calendar. Everything is claimed over REST.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { SkillNodeDef } from "../../api/types";
import { itemIcon, itemName } from "../../game/items";
import { sfx } from "../../game/sfx";
import {
  journalDots,
  useJournal,
  type AchievementView,
  type CalendarDay,
  type JournalTab,
  type MainQuestView,
  type QuestView,
  type SkillsView,
} from "../../state/journal";
import { serverNow, useSession } from "../../state/session";
import { toast } from "../../state/toasts";
import { useVillage } from "../../state/village";
import { formatDuration, Icon, Modal } from "../components/kit";
import { SpriteThumb } from "../components/SpriteThumb";
import { CompanionsTab, TrophyHallTab } from "./Companions";

async function post<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    return await api<T>(path, { method: "POST", body });
  } catch (e) {
    toast(e instanceof ApiError ? e.message : "That didn't work.", "bad");
    return null;
  }
}

/** Coins land in the wallet the village view shows: refresh it after a payout. */
function refreshAfterReward(): void {
  void useJournal.getState().fetch();
  void useVillage.getState().fetch().catch(() => undefined);
}

function Meter({ value, max, done }: { value: number; max: number; done?: boolean }) {
  return (
    <span className="meter" role="meter" aria-valuenow={value} aria-valuemax={max}>
      <span style={{ width: `${Math.min(1, value / Math.max(1, max)) * 100}%`, background: done ? "var(--leaf)" : "var(--gold)" }} />
    </span>
  );
}

// ── quests ───────────────────────────────────────────────────────────────────

function QuestRow({ q, period }: { q: QuestView; period: "daily" | "weekly" }) {
  const [busy, setBusy] = useState(false);
  const claim = async () => {
    setBusy(true);
    const r = await post<{ got: { xp: number; coins: number; token: number } }>("/api/journal/quests/claim", { period, key: q.key });
    setBusy(false);
    if (!r) return;
    sfx("coin");
    toast(`Quest done! +${r.got.xp} XP, +${r.got.coins} coins${r.got.token ? `, +${r.got.token} cosmetic token` : ""}`, "good", "scroll");
    refreshAfterReward();
  };
  return (
    <div className={`slot quest-row col ${q.claimed ? "claimed" : q.done ? "ready" : ""}`}>
      <div className="row" style={{ gap: 8 }}>
        <Icon name={q.claimed ? "check" : "scroll"} scale={1.5} />
        <span className="head grow">{q.title}</span>
        <span className="small">{q.progress.toLocaleString()} / {q.target.toLocaleString()}</span>
      </div>
      <Meter value={q.progress} max={q.target} done={q.done} />
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="small muted grow">
          {q.reward.xp} XP · {q.reward.coins[0]}–{q.reward.coins[1]} <Icon name="coins" scale={1} />
          {q.reward.token ? <> · {q.reward.token} token</> : null}
        </span>
        {q.claimed ? <span className="small head">Claimed</span> : q.done ? (
          <button className="btn small gold" disabled={busy} onClick={claim}>Claim</button>
        ) : null}
      </div>
    </div>
  );
}

function MainQuest({ m }: { m: MainQuestView | null }) {
  const [busy, setBusy] = useState(false);
  if (!m) {
    return (
      <div className="slot main-quest col">
        <span className="head"><Icon name="star" scale={1.5} /> The story so far</span>
        <span className="small">You've finished every chapter. The realm sings your name!</span>
      </div>
    );
  }
  const claim = async () => {
    setBusy(true);
    const r = await post<{ got: { xp: number; coins: number; title: string | null } }>("/api/journal/quests/claim", { period: "main", key: m.key });
    setBusy(false);
    if (!r) return;
    sfx("fanfare");
    toast(`Chapter complete! +${r.got.xp} XP, +${r.got.coins} coins${r.got.title ? `, title “${r.got.title}”` : ""}`, "good", "star");
    refreshAfterReward();
  };
  return (
    <div className={`slot main-quest col ${m.done ? "ready" : ""}`}>
      <span className="small muted">Chapter {m.index + 1} of {m.total}</span>
      <div className="row" style={{ gap: 8 }}>
        <Icon name="star" scale={2} />
        <span className="head grow" style={{ fontSize: 18 }}>{m.title}</span>
        <span className="small">{m.progress.toLocaleString()} / {m.target.toLocaleString()}</span>
      </div>
      <Meter value={m.progress} max={m.target} done={m.done} />
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="small muted grow">
          {m.reward.xp ? `${m.reward.xp} XP · ` : ""}{m.reward.coins ? <>{m.reward.coins} <Icon name="coins" scale={1} /></> : null}
          {m.reward.title ? <> · title <b>“{m.reward.title}”</b></> : null}
        </span>
        {m.done && <button className="btn small gold" disabled={busy} onClick={claim}>Claim</button>}
      </div>
    </div>
  );
}

function QuestsTab() {
  const q = useJournal((s) => s.view!.quests);
  const now = serverNow();
  return (
    <div className="col" style={{ gap: 10 }}>
      <MainQuest m={q.main} />
      <div className="quest-cols">
        <div className="col" style={{ gap: 6 }}>
          <span className="head row" style={{ gap: 6 }}>
            <Icon name="sun" scale={1.5} /> Today <span className="grow" />
            <span className="small muted">new in {formatDuration(Math.max(0, (q.resets.daily_ms - now) / 1000))}</span>
          </span>
          {q.daily.map((x) => <QuestRow key={x.key} q={x} period="daily" />)}
        </div>
        <div className="col" style={{ gap: 6 }}>
          <span className="head row" style={{ gap: 6 }}>
            <Icon name="calendar" scale={1.5} /> This week <span className="grow" />
            <span className="small muted">new in {formatDuration(Math.max(0, (q.resets.weekly_ms - now) / 1000))}</span>
          </span>
          {q.weekly.map((x) => <QuestRow key={x.key} q={x} period="weekly" />)}
        </div>
      </div>
    </div>
  );
}

// ── skills ───────────────────────────────────────────────────────────────────

const WHY: Record<string, string> = {
  maxed: "Maxed",
  no_points: "No points",
  locked: "Locked",
  unknown_skill: "?",
};

function depthOf(nodes: Record<string, SkillNodeDef>, key: string, seen = new Set<string>()): number {
  const n = nodes[key];
  if (!n || !n.requires.length || seen.has(key)) return 0;
  seen.add(key);
  return 1 + Math.max(...n.requires.map((r) => depthOf(nodes, r, seen)));
}

function SkillNode({ k, n, sk, nodes, onLearn, busy }: {
  k: string;
  n: SkillNodeDef;
  sk: SkillsView;
  nodes: Record<string, SkillNodeDef>;
  onLearn: (k: string) => void;
  busy: boolean;
}) {
  const rank = sk.ranks[k] ?? 0;
  const why = sk.can[k];
  const needs = n.requires.filter((r) => !(sk.ranks[r] > 0)).map((r) => nodes[r]?.name ?? r);
  return (
    <div className={`slot skill-node col ${rank > 0 ? "learned" : ""} ${why === "locked" ? "locked" : ""} ${n.branch_points ? "capstone" : ""}`}>
      <span className="head">{n.name}</span>
      <span className="row" style={{ gap: 6 }}>
        <span className="pips" aria-label={`Rank ${rank} of ${n.max}`}>
          {Array.from({ length: n.max }, (_, i) => <span key={i} className={i < rank ? "on" : ""} />)}
        </span>
        <span className="rank">{rank}/{n.max}</span>
      </span>
      <span className="small">{n.desc}</span>
      {why === "locked" && (
        <span className="small muted">
          <Icon name="lock" scale={1} /> {needs.length ? `Needs ${needs.join(" and ")}` : `Needs ${n.branch_points} points in this branch`}
        </span>
      )}
      <button className="btn small" disabled={busy || why !== null} onClick={() => onLearn(k)}>
        {why === null ? <><Icon name="plus" scale={1} /> Learn</> : WHY[why] ?? why}
      </button>
    </div>
  );
}

function SkillsTab() {
  const config = useSession((s) => s.config)!;
  const sk = useJournal((s) => s.view!.skills);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const free = sk.points - sk.spent;
  const setSkills = (next: SkillsView) => useJournal.setState((s) => ({ view: s.view ? { ...s.view, skills: next } : s.view }));
  const learn = async (key: string) => {
    setBusy(true);
    const r = await post<SkillsView>("/api/journal/skills/learn", { key });
    setBusy(false);
    if (!r) return;
    sfx("shimmer");
    setSkills(r);
  };
  const respec = async () => {
    if (!confirm) return setConfirm(true);
    setConfirm(false);
    setBusy(true);
    const r = await post<SkillsView & { cost: number }>("/api/journal/skills/respec");
    setBusy(false);
    if (!r) return;
    sfx("poof");
    toast(r.cost ? `Skills reset for ${r.cost} coins.` : "Skills reset. That one was free!", "good", "skill");
    setSkills(r);
    void useVillage.getState().fetch().catch(() => undefined);
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row skills-head" style={{ gap: 10, flexWrap: "wrap" }}>
        <span className="head" style={{ fontSize: 18 }}>
          <Icon name="skill" scale={1.5} /> {free} point{free === 1 ? "" : "s"} to spend
        </span>
        <span className="small muted grow">You get {config.skills.points_per_level} per level · {sk.spent} spent of {sk.points}</span>
        <button className={`btn small ${confirm ? "danger" : "secondary"}`} disabled={busy || sk.spent === 0} onClick={respec}>
          {confirm ? `Sure? ${sk.respec_cost ? `${sk.respec_cost} coins` : "Free"}` : <>Reset {sk.respec_cost ? <>({sk.respec_cost} <Icon name="coins" scale={1} />)</> : "(free)"}</>}
        </button>
      </div>
      <div className="skill-branches">
        {Object.entries(config.skills.branches).map(([bk, br]) => {
          const rows: string[][] = [];
          for (const k of Object.keys(br.nodes)) {
            const d = depthOf(br.nodes, k);
            (rows[d] ??= []).push(k);
          }
          const spentHere = Object.keys(br.nodes).reduce((a, k) => a + (sk.ranks[k] ?? 0), 0);
          return (
            <div key={bk} className={`skill-branch col branch-${bk}`}>
              <span className="head row" style={{ gap: 6 }}>
                {br.name} <span className="grow" /> <span className="small muted">{spentHere} spent</span>
              </span>
              {rows.map((keys, i) => (
                <div key={i} className="skill-row">
                  {keys.map((k) => <SkillNode key={k} k={k} n={br.nodes[k]} sk={sk} nodes={br.nodes} onLearn={learn} busy={busy} />)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── achievements and titles ──────────────────────────────────────────────────

function AchievementCard({ a }: { a: AchievementView }) {
  const [busy, setBusy] = useState(false);
  const claim = async () => {
    setBusy(true);
    const r = await post<{ got: { coins: number; title: string | null } }>("/api/journal/achievements/claim", { key: a.key });
    setBusy(false);
    if (!r) return;
    sfx("fanfare");
    toast(`${a.name}! +${r.got.coins} coins${r.got.title ? `, title “${r.got.title}”` : ""}`, "good", "trophy");
    refreshAfterReward();
  };
  return (
    <div className={`slot ach-card col ${a.unlocked ? "unlocked" : "locked"} ${a.claimed ? "claimed" : ""}`}>
      <div className="row" style={{ gap: 6 }}>
        <Icon name={a.unlocked ? "trophy" : "lock"} scale={1.5} />
        <span className="head grow">{a.name}</span>
      </div>
      <span className="small">{a.desc}</span>
      {!a.unlocked && <Meter value={a.progress} max={a.target} />}
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        <span className="small muted grow">
          {a.coins} <Icon name="coins" scale={1} />{a.title ? <> · “{a.title}”</> : null}
        </span>
        {a.claimed ? <Icon name="check" scale={1.5} title="Claimed" /> : a.unlocked ? (
          <button className="btn small gold" disabled={busy} onClick={claim}>Claim</button>
        ) : (
          <span className="small muted">{a.progress.toLocaleString()} / {a.target.toLocaleString()}</span>
        )}
      </div>
    </div>
  );
}

function AchievementsTab() {
  const a = useJournal((s) => s.view!.achievements);
  const [busy, setBusy] = useState(false);
  const wear = async (title: string | null) => {
    setBusy(true);
    const r = await post("/api/journal/title", { title });
    setBusy(false);
    if (r === null) return;
    sfx("pickup");
    toast(title ? `You're now known as “${title}”.` : "Title hidden.", "good", "star");
    useJournal.setState((s) => (s.view ? { view: { ...s.view, achievements: { ...s.view.achievements, title } } } : s));
  };
  const sorted = useMemo(
    () => [...a.achievements].sort((x, y) => Number(y.unlocked && !y.claimed) - Number(x.unlocked && !x.claimed) || Number(y.unlocked) - Number(x.unlocked)),
    [a.achievements],
  );
  const got = a.achievements.filter((x) => x.unlocked).length;
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="slot col title-picker" style={{ gap: 6 }}>
        <span className="head">Your title <span className="small muted">shows on your nameplate</span></span>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <button className={`btn small ${a.title ? "secondary" : ""}`} disabled={busy} onClick={() => wear(null)}>None</button>
          {a.titles.map((t) => (
            <button key={t} className={`btn small ${a.title === t ? "gold" : "secondary"}`} disabled={busy} onClick={() => wear(t)}>{t}</button>
          ))}
          {a.titles.length === 0 && <span className="small muted">Earn titles from achievements, the story and the login calendar.</span>}
        </div>
      </div>
      <span className="small muted">{got} of {a.achievements.length} unlocked</span>
      <div className="ach-grid">
        {sorted.map((x) => <AchievementCard key={x.key} a={x} />)}
      </div>
    </div>
  );
}

// ── the collection book ──────────────────────────────────────────────────────

interface Entry { key: string; name: string; icon?: string; count: number; boss?: boolean | string }
interface CollectionView {
  bestiary: Entry[];
  materials: Entry[];
  gear: Entry[];
  brews: Entry[];
  trophies: (Entry & { boss: string })[];
  fish: Entry[];
  combos: { found: string[]; total: number };
  lore: { found: number; keys: string[] };
}

function Shelf({ title, entries, verb, sprite }: { title: string; entries: Entry[]; verb: string; sprite?: (e: Entry) => string }) {
  const found = entries.filter((e) => e.count > 0).length;
  return (
    <div className="col" style={{ gap: 4 }}>
      <span className="head row" style={{ gap: 6 }}>{title} <span className="small muted">{found} / {entries.length}</span></span>
      <div className="shelf">
        {entries.map((e) => (
          <div key={e.key} className={`slot shelf-cell col ${e.count ? "" : "unknown"}`} title={e.count ? `${e.name}: ${e.count.toLocaleString()} ${verb}` : "Not found yet"}>
            {sprite ? <SpriteThumb name={sprite(e)} box={40} maxScale={2} silhouette={!e.count} /> : (
              <span style={{ opacity: e.count ? 1 : 0.25, filter: e.count ? undefined : "brightness(0)" }}><Icon name={(e.icon ?? "info").replace(/^icon\./, "")} scale={2} /></span>
            )}
            <span className="small shelf-name">{e.count ? e.name : "???"}</span>
            {e.count > 0 && <span className="small muted">{e.count.toLocaleString()}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function CollectionTab() {
  const [c, setC] = useState<CollectionView | null>(null);
  useEffect(() => {
    api<CollectionView>("/api/journal/collection").then(setC).catch(() => toast("The book's pages are stuck.", "bad"));
  }, []);
  if (!c) return <p>Turning pages…</p>;
  const monsters = c.bestiary.filter((e) => !e.boss);
  const bosses = c.bestiary.filter((e) => e.boss);
  return (
    <div className="col collection" style={{ gap: 10 }}>
      <div className="row small" style={{ gap: 12, flexWrap: "wrap" }}>
        <span><b>{c.combos.found.length}</b> / {c.combos.total} building combos found</span>
        <span><b>{c.lore.found}</b> lore stones read</span>
      </div>
      <Shelf title="Bestiary" entries={monsters} verb="defeated" sprite={(e) => `mon.${e.key}.idle.0`} />
      <Shelf title="Bosses" entries={bosses} verb="defeated" sprite={(e) => `mon.${e.key}.idle.0`} />
      <Shelf title="Trophies" entries={c.trophies} verb="won" />
      <Shelf title="Materials" entries={c.materials} verb="gathered" />
      <Shelf title="Gear" entries={c.gear.map((g) => ({ ...g, icon: `icon.${itemIcon(g.key)}` }))} verb="forged" />
      <Shelf title="Brews and meals" entries={c.brews} verb="made" />
      <Shelf title="Fish" entries={c.fish} verb="caught" />
    </div>
  );
}

// ── the login calendar ───────────────────────────────────────────────────────

function DayRewards({ d }: { d: CalendarDay }) {
  const config = useSession((s) => s.config)!;
  return (
    <span className="day-rewards row">
      {d.coins > 0 && <span className="row" title={`${d.coins} coins`}><Icon name="coins" scale={1} />{d.coins}</span>}
      {Object.entries(d.res).map(([k, q]) => (
        <span key={k} className="row" title={config.resources[k]?.name ?? k}><Icon name={config.resources[k]?.icon.replace("icon.", "") ?? k} scale={1} />{q}</span>
      ))}
      {Object.entries(d.items).map(([k, q]) => (
        <span key={k} className="row" title={itemName(k)}><Icon name={itemIcon(k)} scale={1} />{q}</span>
      ))}
    </span>
  );
}

function CalendarTab() {
  const cal = useJournal((s) => s.view!.calendar);
  const [busy, setBusy] = useState(false);
  const claim = async () => {
    setBusy(true);
    const r = await post<{ got: CalendarDay & { day: number } }>("/api/journal/calendar/claim");
    setBusy(false);
    if (!r) return;
    sfx(r.got.title ? "fanfare" : "coin");
    toast(`Day ${r.got.day} collected!${r.got.title ? ` New title: “${r.got.title}”` : ""}`, "good", "calendar");
    refreshAfterReward();
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="small grow">
          Log in and collect one day at a time. Miss a day and nothing's lost: the calendar just waits.
          {cal.round > 0 && <b> Round {cal.round + 1}.</b>}
        </span>
        <button className="btn gold small" disabled={busy || cal.claimed_today} onClick={claim}>
          <Icon name="calendar" scale={1.5} /> {cal.claimed_today ? "Back tomorrow" : `Collect day ${cal.day + 1}`}
        </button>
      </div>
      <div className="calendar-grid">
        {cal.days.map((d, i) => {
          const state = i < cal.day ? "done" : i === cal.day ? (cal.claimed_today ? "next" : "today") : "later";
          return (
            <div key={i} className={`slot cal-day col ${state} ${d.title ? "big" : ""}`}>
              <span className="row" style={{ gap: 4 }}>
                <span className="head">Day {i + 1}</span>
                <span className="grow" />
                {state === "done" && <Icon name="check" scale={1} />}
              </span>
              <DayRewards d={d} />
              {d.title && <span className="small cal-title">“{d.title}”</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── the panel ────────────────────────────────────────────────────────────────

const TABS: { key: JournalTab; label: string; icon: string }[] = [
  { key: "quests", label: "Quests", icon: "scroll" },
  { key: "skills", label: "Skills", icon: "skill" },
  { key: "achievements", label: "Feats", icon: "star" },
  { key: "pets", label: "Pets", icon: "paw" },
  { key: "trophies", label: "Trophies", icon: "trophy" },
  { key: "collection", label: "Collection", icon: "book" },
  { key: "calendar", label: "Calendar", icon: "calendar" },
];

export function JournalPanel({ onClose }: { onClose: () => void }) {
  const tab = useJournal((s) => s.tab) ?? "quests";
  const view = useJournal((s) => s.view);
  const fetch = useJournal((s) => s.fetch);
  const [, force] = useState(0);
  useEffect(() => {
    void fetch();
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [fetch]);
  const dots = journalDots(view);
  return (
    <Modal title="Journal" onClose={onClose} wide>
      <div className="row tabs journal-tabs" role="tablist" style={{ gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={`btn small ${tab === t.key ? "" : "secondary"}`}
            aria-label={t.label} title={t.label} onClick={() => useJournal.getState().set({ tab: t.key })}>
            <Icon name={t.icon} scale={1.5} /> <span className="tab-label">{t.label}</span>
            {dots[t.key] > 0 && <span className="dot-count">{t.key === "skills" || t.key === "calendar" ? "!" : dots[t.key]}</span>}
          </button>
        ))}
      </div>
      {!view ? <p>Opening the journal…</p> : tab === "quests" ? <QuestsTab /> : tab === "skills" ? <SkillsTab />
        : tab === "achievements" ? <AchievementsTab /> : tab === "pets" ? <CompanionsTab /> : tab === "trophies" ? <TrophyHallTab />
        : tab === "collection" ? <CollectionTab /> : <CalendarTab />}
    </Modal>
  );
}

/** The HUD button, with a count of things waiting to be collected. Opens on the tab that needs you. */
export function JournalButton({ iconOnly = false }: { iconOnly?: boolean }) {
  const view = useJournal((s) => s.view);
  const dots = journalDots(view);
  const n = dots.quests + dots.achievements + dots.calendar + dots.skills;
  const first = (["quests", "achievements", "calendar", "skills"] as JournalTab[]).find((t) => dots[t] > 0) ?? "quests";
  return (
    <button className={`btn secondary has-dot ${iconOnly ? "icon-only" : ""}`} onClick={() => useJournal.getState().set({ tab: first })}
      aria-label={`Journal${n ? ` (${n} to collect)` : ""}`} title="Journal: quests, skills, feats, calendar (J)" data-tut-target="journal">
      <Icon name="scroll" /> {!iconOnly && <span className="hide-narrow">Journal</span>}
      {n > 0 && <span className="dot-count">{n}</span>}
    </button>
  );
}
