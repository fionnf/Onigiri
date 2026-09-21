import { api } from "@/api/client";
import { ErrorBox } from "@/components/ui";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const signIn = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: onSignedIn,
  });

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <form
        className="card w-full max-w-sm space-y-4 p-6"
        onSubmit={(event) => {
          event.preventDefault();
          signIn.mutate();
        }}
      >
        <div className="flex items-center gap-2">
          <img src="/icon.svg" alt="" className="h-7 w-7 rounded" />
          <div>
            <h1 className="text-base font-semibold">Onigiri</h1>
            <p className="text-xs text-muted">Your recipe bank.</p>
          </div>
        </div>

        <label className="block space-y-1">
          <span className="label">Email</span>
          <input
            className="field"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>

        <label className="block space-y-1">
          <span className="label">Password</span>
          <input
            className="field"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {signIn.isError && <ErrorBox error={signIn.error} />}

        <button type="submit" className="btn btn-primary w-full" disabled={signIn.isPending}>
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
