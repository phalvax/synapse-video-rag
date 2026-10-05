import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./ui";

export type Screen = "recherche" | "missions" | "upload" | "dashboard";

const NAV: { id: Screen; label: string; icon: () => ReactNode }[] = [
  { id: "recherche", label: "Recherche", icon: Icon.search },
  { id: "missions", label: "Point mission", icon: Icon.mission },
  { id: "upload", label: "Importer", icon: Icon.upload },
  { id: "dashboard", label: "Indicateurs", icon: Icon.chart },
];

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "dark" || set === "light") return set;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

interface Props {
  active: Screen;
  onChange: (s: Screen) => void;
  children: ReactNode;
}

export default function Layout({ active, onChange, children }: Props) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("rag16-theme", theme);
    } catch {
      // stockage indisponible (navigation privée…) : le thème vaut pour cette session
    }
  }, [theme]);

  return (
    <div className="min-h-screen bg-bg">
      <aside className="fixed inset-y-0 left-0 flex w-56 flex-col border-r border-line bg-surface px-3 py-5">
        <div className="flex items-center gap-2.5 px-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-ink">
            <Icon.wave />
          </span>
          <div className="leading-tight">
            <p className="text-[15px] font-semibold tracking-tight text-ink">RAG16</p>
            <p className="text-xs text-muted">Mémoire des réunions</p>
          </div>
        </div>

        <nav className="mt-8 flex flex-col gap-1" aria-label="Écrans">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => onChange(n.id)}
              aria-current={active === n.id ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                active === n.id
                  ? "bg-accent-soft text-accent"
                  : "text-ink-2 hover:bg-surface-2 hover:text-ink"
              }`}
            >
              <n.icon />
              {n.label}
            </button>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-3 px-2">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="flex items-center gap-2 rounded-lg px-1 py-1.5 text-sm text-muted hover:text-ink"
            aria-label={theme === "dark" ? "Passer en thème clair" : "Passer en thème sombre"}
          >
            {theme === "dark" ? <Icon.sun /> : <Icon.moon />}
            {theme === "dark" ? "Thème clair" : "Thème sombre"}
          </button>
          <p className="text-[11px] leading-snug text-muted">
            Équipe 16 · Albert School × Synchrone
          </p>
        </div>
      </aside>

      <main className="ml-56 min-h-screen px-10 py-8">
        <div key={active} className="anim-in mx-auto max-w-[1320px]">
          {children}
        </div>
      </main>
    </div>
  );
}
