import { useState, type FormEvent } from "react";
import { useAuth } from "../hooks/useAuth";
import { ErrorBanner } from "../components/Feedback";

export function LoginPage() {
  const { signIn } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (username.trim().length < 3 || password.length < 8) {
      setError("Use a username of at least 3 characters and a password of at least 8.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password, mode === "register");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="font-serif text-4xl font-semibold tracking-tight">Memora</h1>
        <p className="mt-2 text-graphite">
          A learning assistant that remembers how you learn, shows what it remembered, and forgets when you ask.
        </p>
        <form onSubmit={submit} className="mt-8 space-y-3" noValidate>
          <label className="block text-sm font-bold">Username
            <input className="field mt-1" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          </label>
          <label className="block text-sm font-bold">Password
            <input className="field mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </label>
          {error && <ErrorBanner message={error} />}
          <button className="btn-primary w-full justify-center py-2" disabled={busy}>
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
        <div className="mt-4 flex justify-between text-sm">
          <button className="text-cobalt hover:underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create an account" : "I already have an account"}
          </button>
          <button className="text-cobalt hover:underline" onClick={() => { setUsername("demo"); setPassword("memora-demo"); setMode("login"); }}>
            Fill in the demo account
          </button>
        </div>
      </div>
    </div>
  );
}
