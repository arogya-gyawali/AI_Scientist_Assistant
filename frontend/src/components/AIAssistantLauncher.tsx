import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { AIAssistantPanel } from "./AIAssistantPanel";

/**
 * Global floating AI Assistant trigger.
 * Sits bottom-right on every route and opens the slide-in chat panel.
 * The panel is context-aware via the current route (passed down).
 */
export const AIAssistantLauncher = () => {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open AI assistant"
        className="group fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 rounded-full border border-ink/20 bg-ink px-4 py-3 text-paper shadow-[0_8px_24px_-8px_hsl(var(--ink)/0.45)] transition-all hover:-translate-y-0.5 hover:shadow-[0_12px_28px_-8px_hsl(var(--ink)/0.55)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-paper sm:bottom-8 sm:right-8"
      >
        <span
          aria-hidden
          className="flex h-6 w-6 items-center justify-center rounded-full bg-paper/10"
        >
          <Sparkles className="h-3.5 w-3.5 text-paper" strokeWidth={1.75} />
        </span>
        <span className="font-mono-notebook text-[11px] uppercase tracking-[0.22em]">
          Ask AI
        </span>
      </button>

      <AIAssistantPanel
        open={open}
        onOpenChange={setOpen}
        route={pathname}
      />
    </>
  );
};

export default AIAssistantLauncher;
