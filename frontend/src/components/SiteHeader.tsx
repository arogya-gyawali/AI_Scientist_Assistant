import { Link, useLocation } from "react-router-dom";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/drafts", label: "Drafts" },
  { to: "/library", label: "Library" },
  { to: "/account", label: "Account" },
];

const SiteHeader = () => {
  const { pathname } = useLocation();

  return (
    <header className="relative border-b border-rule">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-10">
        <Link to="/" className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex h-7 w-7 items-center justify-center rounded-sm border border-rule bg-paper-raised"
          >
            <FlaskConical className="h-4 w-4 text-primary" strokeWidth={1.5} />
          </span>
          <span className="font-serif-display text-xl tracking-tight text-ink">
            Praxis
          </span>
        </Link>
        <nav className="hidden items-center gap-7 text-sm text-muted-foreground sm:flex">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "transition-colors hover:text-ink",
                  active && "text-ink",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
};

export default SiteHeader;
