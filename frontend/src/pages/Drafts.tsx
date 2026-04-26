import { useNavigate } from "react-router-dom";
import { ArrowRight, Trash2 } from "lucide-react";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";

type Draft = {
  id: string;
  title: string;
  status: string;
  edited: string;
  preview: string;
};

const DRAFTS: Draft[] = [
  {
    id: "d1",
    title: "Cryopreservation of HeLa cells with trehalose",
    status: "Step 2 — Literature review",
    edited: "Edited 2 hours ago",
    preview:
      "Testing whether intracellular trehalose loading improves post-thaw viability versus standard DMSO protocols.",
  },
  {
    id: "d2",
    title: "Glucose dose–response in E. coli K-12 MG1655",
    status: "Step 1 — Hypothesis drafting",
    edited: "Edited yesterday",
    preview:
      "Mapping specific growth rate µ across 0–25 mM glucose in M9 minimal media at 37 °C, aerobic.",
  },
  {
    id: "d3",
    title: "CRISPR knockdown of TP53 in MCF-7",
    status: "Step 3 — Protocol drafting",
    edited: "Edited 3 days ago",
    preview:
      "Comparing dCas9-KRAB knockdown efficiency against shRNA controls for proliferation phenotype.",
  },
  {
    id: "d4",
    title: "Biofilm formation under shear stress",
    status: "Step 2 — Literature review",
    edited: "Edited last week",
    preview:
      "Quantifying P. aeruginosa biofilm thickness in microfluidic channels at varying flow rates.",
  },
];

const Drafts = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-paper text-ink">
      <SiteHeader />

      <main className="mx-auto max-w-5xl px-6 pb-24 pt-12 sm:px-10 sm:pt-16">
        <header className="mb-10">
          <p className="mb-2 text-sm uppercase tracking-[0.18em] text-muted-foreground">
            Workspace
          </p>
          <h1 className="font-serif-display text-5xl text-ink">Drafts</h1>
          <p className="mt-3 max-w-2xl text-base text-muted-foreground">
            Work in progress experiments and hypotheses. Pick up where you left off.
          </p>
        </header>

        <ul className="space-y-5">
          {DRAFTS.map((draft) => (
            <li
              key={draft.id}
              className="rounded-lg border border-rule bg-paper-raised shadow-sm"
            >
              <div className="flex flex-col gap-5 p-7 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="mb-2 flex flex-wrap items-center gap-3">
                    <span className="rounded-full border border-rule bg-paper px-3 py-1 text-xs font-medium text-ink-soft">
                      {draft.status}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {draft.edited}
                    </span>
                  </div>
                  <h2 className="font-serif-card text-2xl text-ink">
                    {draft.title}
                  </h2>
                  <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-soft/80">
                    {draft.preview}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                  <Button
                    onClick={() => navigate("/lab")}
                    className="bg-primary text-primary-foreground hover:bg-primary/90"
                  >
                    Continue
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
};

export default Drafts;
