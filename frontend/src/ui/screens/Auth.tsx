import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import type { Appearance, SignupResult } from "../../api/types";
import { manifest } from "../../assets/manifest";
import { useSession } from "../../state/session";
import { CharacterPreview, Icon, Panel, Stepper, Swatches } from "../components/kit";

function Title({ children }: { children: React.ReactNode }) {
  return (
    <div className="title-bg">
      <div className="col" style={{ width: "min(460px, 100%)", gap: 18, alignItems: "stretch" }}>
        <div className="col" style={{ gap: 6, alignItems: "center" }}>
          <div className="logo">Hearthforge</div>
          <div className="panel-dark tagline" style={{ color: "var(--paper-light)" }}>
            Build your village. Forge your legend.
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

export function LoginScreen() {
  const nav = useNavigate();
  const setLoggedIn = useSession((s) => s.setLoggedIn);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ csrf_token: string }>("/api/auth/login", { method: "POST", body: { username, password } });
      await setLoggedIn(r.csrf_token);
      nav("/play");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Title>
      <Panel>
        <form className="col" onSubmit={submit} style={{ gap: 12 }}>
          <h2>Welcome back</h2>
          <div className="field">
            <label htmlFor="u">Username</label>
            <input id="u" className="input" autoComplete="username" value={username}
              onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="p">Password</label>
            <input id="p" className="input" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div className="hint bad" role="alert">{error}</div>}
          <button className="btn block" disabled={busy}>
            <Icon name="home" /> Enter your village
          </button>
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <Link to="/recover" className="small">Forgot your password?</Link>
          </div>
        </form>
      </Panel>
      <Panel>
        <div className="col" style={{ gap: 8 }}>
          <h3>New here?</h3>
          <p className="muted small" style={{ margin: 0 }}>All you need is a name and a password. No email.</p>
          <button className="btn gold block" onClick={() => nav("/signup")}>
            <Icon name="build" /> Found a new village
          </button>
        </div>
      </Panel>
    </Title>
  );
}

function useUsernameCheck(name: string) {
  const [state, setState] = useState<{ ok: boolean | null; reason: string | null }>({ ok: null, reason: null });
  useEffect(() => {
    if (!name) {
      setState({ ok: null, reason: null });
      return;
    }
    const t = window.setTimeout(async () => {
      try {
        const r = await api<{ ok: boolean; reason: string | null }>(
          `/api/auth/username-available?name=${encodeURIComponent(name)}`,
        );
        setState(r);
      } catch {
        setState({ ok: null, reason: null });
      }
    }, 300);
    return () => window.clearTimeout(t);
  }, [name]);
  return state;
}

export function SignupScreen() {
  const nav = useNavigate();
  const config = useSession((s) => s.config);
  const setLoggedIn = useSession((s) => s.setLoggedIn);
  const [step, setStep] = useState<"name" | "look" | "codes">("name");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [look, setLook] = useState<Appearance | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [csrf, setCsrfToken] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const check = useUsernameCheck(username);
  const minPw = config?.game.auth.password_min ?? 8;

  useEffect(() => {
    if (config && !look) setLook(config.avatar.default_appearance);
  }, [config, look]);

  async function create() {
    if (!look) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<SignupResult>("/api/auth/signup", {
        method: "POST",
        body: { username, password, appearance: look },
      });
      setCodes(r.recovery_codes);
      setCsrfToken(r.csrf_token);
      setStep("codes");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      if (err instanceof ApiError && (err.code === "username_taken" || err.code === "bad_username")) setStep("name");
    } finally {
      setBusy(false);
    }
  }

  if (step === "look" && look && config) {
    return (
      <div className="title-bg">
        <CharacterCreator look={look} setLook={setLook} onBack={() => setStep("name")} onDone={create} busy={busy}
          error={error} doneLabel="Found my village" />
      </div>
    );
  }

  if (step === "codes") {
    return (
      <Title>
        <Panel>
          <div className="col" style={{ gap: 10 }}>
            <h2>Your recovery codes</h2>
            <p className="small" style={{ margin: 0 }}>
              We don't ask for your email, so these are the <b>only</b> way back in if you forget your password.
              Each code works once. Write them down or screenshot them.
            </p>
            <div className="codes">
              {codes.map((c) => (
                <span key={c} className="slot">{c}</span>
              ))}
            </div>
            <div className="row">
              <button className="btn secondary small" onClick={() => navigator.clipboard?.writeText(codes.join("\n"))}>
                Copy all
              </button>
              <label className="row small" style={{ gap: 8 }}>
                <input type="checkbox" className="toggle" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
                I saved them
              </label>
            </div>
            <button className="btn gold block" disabled={!saved} onClick={async () => {
              await setLoggedIn(csrf);
              nav("/play");
            }}>
              <Icon name="home" /> Enter your village
            </button>
          </div>
        </Panel>
      </Title>
    );
  }

  const canNext = check.ok === true && password.length >= minPw;
  return (
    <Title>
      <Panel>
        <form className="col" style={{ gap: 12 }} onSubmit={(e) => {
          e.preventDefault();
          if (canNext) {
            setError(null);
            setStep("look");
          }
        }}>
          <h2>Found a village</h2>
          <div className="field">
            <label htmlFor="su">Pick a name</label>
            <input id="su" className="input" autoComplete="username" value={username} maxLength={20}
              onChange={(e) => setUsername(e.target.value.trim())} placeholder="e.g. Mossbeard" required />
            <span className={`hint ${check.ok ? "ok" : check.ok === false ? "bad" : ""}`}>
              {check.ok ? "That name is free!" : check.reason ?? "Letters, numbers and underscores."}
            </span>
          </div>
          <div className="field">
            <label htmlFor="sp">Password</label>
            <input id="sp" className="input" type="password" autoComplete="new-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
            <span className={`hint ${password && password.length < minPw ? "bad" : ""}`}>
              At least {minPw} characters.
            </span>
          </div>
          {error && <div className="hint bad" role="alert">{error}</div>}
          <button className="btn block" disabled={!canNext}>Next: create your hero ▶</button>
          <Link to="/" className="small">Back to login</Link>
        </form>
      </Panel>
    </Title>
  );
}

export function CharacterCreator({ look, setLook, onBack, onDone, busy, error, doneLabel }: {
  look: Appearance;
  setLook: (a: Appearance) => void;
  onBack?: () => void;
  onDone: () => void;
  busy?: boolean;
  error?: string | null;
  doneLabel: string;
}) {
  const config = useSession((s) => s.config)!;
  const cr = config.avatar.creator;
  const rc = manifest.recolor;
  const [dir, setDir] = useState<"down" | "left" | "up" | "right">("down");
  const dirs = ["down", "left", "up", "right"] as const;
  const set = (k: keyof Appearance) => (v: string) => setLook({ ...look, [k]: v });
  const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];
  const randomize = () =>
    setLook({
      body: pick(cr.bodies), skin: pick(cr.skin_tones), hair_style: pick(cr.hair_styles),
      hair_color: pick(cr.hair_colors), eyes: pick(cr.eye_styles), eye_color: pick(cr.eye_colors),
      outfit: pick(cr.outfits), outfit_color: pick(cr.outfit_colors),
    });
  const previewScale = useMemo(() => (window.innerWidth < 640 ? 5 : 10), []);

  return (
    <div className="panel creator" style={{ width: "min(980px, 100%)" }}>
      <div className="row" style={{ marginBottom: 8, flexWrap: "wrap" }}>
        <span className="ribbon">Create your hero</span>
        <span className="grow" />
        <button className="btn secondary small" onClick={randomize}><Icon name="star" /> Surprise me</button>
      </div>
      <div className="creator-grid">
        <div className="col creator-preview" style={{ alignItems: "center", gap: 8 }}>
          <div className="slot center" style={{ padding: 10, background: "var(--paper)" }}>
            <CharacterPreview look={look} scale={previewScale} dir={dir} />
          </div>
          <div className="row creator-turn">
            <button className="btn secondary small" aria-label="Turn left"
              onClick={() => setDir(dirs[(dirs.indexOf(dir) + 3) % 4])}>⟲</button>
            <span className="head" style={{ minWidth: 60, textAlign: "center", textTransform: "capitalize" }}>{dir}</span>
            <button className="btn secondary small" aria-label="Turn right"
              onClick={() => setDir(dirs[(dirs.indexOf(dir) + 1) % 4])}>⟳</button>
          </div>
        </div>
        <div className="creator-options">
          <div className="field">
            <label>Body</label>
            <div className="row">
              {cr.bodies.map((b) => (
                <button key={b} type="button" className={`btn small secondary ${look.body === b ? "selected" : ""}`}
                  onClick={() => set("body")(b)} style={{ textTransform: "capitalize" }}>{b}</button>
              ))}
            </div>
          </div>
          <Swatches label="Skin" value={look.skin} options={cr.skin_tones} colors={rc.skin} onChange={set("skin")} />
          <Stepper label="Hair" value={look.hair_style} options={cr.hair_styles} onChange={set("hair_style")} />
          <Swatches label="Hair colour" value={look.hair_color} options={cr.hair_colors} colors={rc.hair}
            onChange={set("hair_color")} />
          <Stepper label="Eyes" value={look.eyes} options={cr.eye_styles} onChange={set("eyes")} />
          <Swatches label="Eye colour" value={look.eye_color} options={cr.eye_colors}
            colors={Object.fromEntries(Object.entries(rc.eyes).map(([k, v]) => [k, [v[1], v[1], v[2], v[2]]]))}
            onChange={set("eye_color")} />
          <Stepper label="Outfit" value={look.outfit} options={cr.outfits} onChange={set("outfit")} />
          <Swatches label="Outfit colour" value={look.outfit_color} options={cr.outfit_colors} colors={rc.outfit}
            onChange={set("outfit_color")} />
        </div>
      </div>
      {error && <div className="hint bad" role="alert" style={{ marginTop: 8 }}>{error}</div>}
      <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
        {onBack ? <button className="btn secondary" onClick={onBack}>◀ Back</button> : <span />}
        <button className="btn gold" onClick={onDone} disabled={busy}>
          <Icon name="check" /> {doneLabel}
        </button>
      </div>
    </div>
  );
}

export function RecoverScreen() {
  const nav = useNavigate();
  const setLoggedIn = useSession((s) => s.setLoggedIn);
  const [form, setForm] = useState({ username: "", code: "", new_password: "" });
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState<number | null>(null);
  return (
    <Title>
      <Panel>
        <form className="col" style={{ gap: 12 }} onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            const r = await api<{ csrf_token: string; codes_left: number }>("/api/auth/recover", {
              method: "POST", body: form,
            });
            setLeft(r.codes_left);
            await setLoggedIn(r.csrf_token);
            window.setTimeout(() => nav("/play"), 1200);
          } catch (err) {
            setError(err instanceof ApiError ? err.message : "Something went wrong.");
          }
        }}>
          <h2>Use a recovery code</h2>
          {(["username", "code", "new_password"] as const).map((k) => (
            <div className="field" key={k}>
              <label htmlFor={k}>{k === "new_password" ? "New password" : k === "code" ? "Recovery code" : "Username"}</label>
              <input id={k} className="input" type={k === "new_password" ? "password" : "text"} value={form[k]}
                placeholder={k === "code" ? "ABCDE-FGHJK" : undefined}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })} required />
            </div>
          ))}
          {error && <div className="hint bad" role="alert">{error}</div>}
          {left !== null && <div className="hint ok">Password changed! {left} codes left.</div>}
          <button className="btn block">Reset password</button>
          <Link to="/" className="small">Back to login</Link>
        </form>
      </Panel>
    </Title>
  );
}
