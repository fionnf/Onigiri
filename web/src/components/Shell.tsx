import { api } from "@/api/client";
import { useShortcuts } from "@/lib/hooks";
import { useOnline } from "@/lib/offline";
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
  const online = useOnline();
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

  const reviewBadge =
    stats && stats.needs_review > 0 ? (
      <span
        className="rounded-full bg-warn/15 px-1.5 text-[10px] leading-4 text-warn"
        title={`${stats.needs_review} to review`}
      >
        {stats.needs_review}
      </span>
    ) : null;

  return (
    <div className="flex min-h-full flex-col">
      <header className="safe-top sticky top-0 z-20 border-b border-line bg-page/90 backdrop-blur no-print">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-1 px-4 py-2 sm:px-3">
          <NavLink to="/" className="mr-2 flex items-center gap-2 text-sm font-semibold">
            <img src="/icon.svg" alt="" className="h-6 w-6 rounded sm:h-5 sm:w-5" />
            <span>Onigiri</span>
          </NavLink>

          {/* Wide screens keep the navigation up here; phones get the tab bar below. */}
          <nav className="hidden flex-1 items-center gap-0.5 sm:flex">
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
                <span>{label}</span>
                {label === "Library" && reviewBadge}
              </NavLink>
            ))}
          </nav>
          <span className="flex-1 sm:hidden" />

          {stats && stats.jobs_running > 0 && (
            <NavLink to="/add" className="chip">
              <span className="h-2 w-2 animate-pulse rounded-full bg-warn" />
              {stats.jobs_running} reading
            </NavLink>
          )}
        </div>
      </header>

      {!online && (
        <div className="border-b border-line bg-surface px-4 py-2 text-center text-xs text-muted">
          Offline. Recipes you have opened recently are saved on this phone.
        </div>
      )}

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-28 pt-4 sm:px-3 sm:pb-6">
        {children}
      </main>

      <nav
        aria-label="Main"
        className="safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-line bg-page/95 backdrop-blur no-print sm:hidden"
      >
        <div className="grid grid-cols-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] ${
                  isActive ? "text-ink" : "text-faint"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={`relative flex h-7 w-12 items-center justify-center rounded-full ${
                      to === "/add" ? "bg-accent text-on-accent" : isActive ? "bg-surface" : ""
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    {label === "Library" && reviewBadge && (
                      <span className="absolute -right-1 -top-1">{reviewBadge}</span>
                    )}
                  </span>
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
