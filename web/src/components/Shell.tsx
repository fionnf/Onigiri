import { api } from "@/api/client";
import { useShortcuts } from "@/lib/hooks";
import { useQuery } from "@tanstack/react-query";
import { NavLink, useNavigate } from "react-router-dom";
import { IconBook, IconPlus, IconSettings, IconUser } from "./Icons";

const NAV = [
  { to: "/", label: "Library", icon: IconBook, end: true },
  { to: "/add", label: "Add", icon: IconPlus, end: false },
  { to: "/profile", label: "Profile", icon: IconUser, end: false },
  { to: "/settings", label: "Settings", icon: IconSettings, end: false },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: 30_000,
  });

  useShortcuts({
    n: () => navigate("/add"),
    g: () => navigate("/"),
    "?": () => navigate("/settings#shortcuts"),
  });

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-line bg-page/85 backdrop-blur no-print">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-1 px-3 py-2">
          <NavLink to="/" className="mr-2 flex items-center gap-2 text-sm font-semibold">
            <img src="/icon.svg" alt="" className="h-5 w-5 rounded" />
            <span className="hidden sm:inline">Onigiri</span>
          </NavLink>

          <nav className="flex flex-1 items-center gap-0.5">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `btn btn-ghost btn-sm ${isActive ? "bg-surface text-ink" : "text-muted"}`
                }
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{label}</span>
                {label === "Library" && stats && stats.needs_review > 0 && (
                  <span className="ml-0.5 rounded-full bg-warn/15 px-1.5 text-[10px] text-warn">
                    {stats.needs_review}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          {stats && stats.jobs_running > 0 && (
            <NavLink to="/add" className="chip">
              <span className="h-2 w-2 animate-pulse rounded-full bg-warn" />
              {stats.jobs_running} running
            </NavLink>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-3 py-4">{children}</main>
    </div>
  );
}
