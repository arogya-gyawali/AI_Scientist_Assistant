import { useNavigate } from "react-router-dom";
import { ArrowRight, Copy, Download } from "lucide-react";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";

type SavedExperiment = {
  id: string;
  name: string;
  organism: string;
  method: string;
  summary: string;
  tags: string[];
};

const EXPERIMENTS: SavedExperiment[] = [
  {
    id: "e1",
    name: "Trehalose-mediated cryopreservation of HeLa cells",
    organism: "HeLa cells",
    method: "Cryopreservation assay",
    summary:
      "Comparative viability study of trehalose loading versus DMSO controls across three freeze-thaw cycles.",
    tags: ["Cell Biology", "Diagnostics"],
  },
  {
    id: "e2",
    name: "Glucose catabolite repression in E. coli K-12",
    organism: "E. coli K-12 MG1655",
    method: "Growth rate assay (M9)",
    summary:
      "Dose–response of specific growth rate µ across 0–25 mM glucose under aerobic conditions at 37 °C.",
    tags: ["Microbiology", "Metabolism"],
  },
  {
    id: "e3",
    name: "dCas9-KRAB knockdown of TP53 in MCF-7",
    organism: "MCF-7 breast cancer line",
    method: "CRISPRi proliferation assay",
    summary:
      "Quantifying proliferation phenotypes between dCas9-KRAB and shRNA TP53 knockdown approaches.",
    tags: ["Oncology", "Gene Regulation"],
  },
  {
    id: "e4",
    name: "Biofilm thickness under variable shear",
    organism: "P. aeruginosa PAO1",
    method: "Microfluidic biofilm assay",
    summary:
      "Confocal quantification of biofilm thickness across four flow rates in a microfluidic channel.",
    tags: ["Microbiology", "Biofilm"],
  },
];

const Library = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-paper text-ink">
      <SiteHeader />

      <main className="mx-auto max-w-5xl px-6 pb-24 pt-12 sm:px-10 sm:pt-16">
        <header className="mb-10">
          <p className="mb-2 text-sm uppercase tracking-[0.18em] text-muted-foreground">
            Workspace
          </p>
          <h1 className="font-serif-display text-5xl text-ink">Library</h1>
          <p className="mt-3 max-w-2xl text-base text-muted-foreground">
            Saved and finalized experiment plans, ready to revisit, export, or duplicate.
          </p>
        </header>

        {EXPERIMENTS.length === 0 ? (
          <div className="rounded-lg border border-dashed border-rule bg-paper-raised/60 px-7 py-16 text-center">
            <p className="text-base text-muted-foreground">
              No saved experiments yet
            </p>
          </div>
        ) : (
          <ul className="space-y-5">
            {EXPERIMENTS.map((exp) => (
              <li
                key={exp.id}
                className="rounded-lg border border-rule bg-paper-raised shadow-sm"
              >
                <div className="flex flex-col gap-5 p-7 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <h2 className="font-serif-card text-2xl text-ink">
                      {exp.name}
                    </h2>
                    <dl className="mt-3 flex flex-wrap gap-x-7 gap-y-1.5 text-sm">
                      <div className="flex items-baseline gap-2">
                        <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                          Organism
                        </dt>
                        <dd className="text-ink-soft">{exp.organism}</dd>
                      </div>
                      <div className="flex items-baseline gap-2">
                        <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                          Method
                        </dt>
                        <dd className="text-ink-soft">{exp.method}</dd>
                      </div>
                    </dl>
                    <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-soft/80">
                      {exp.summary}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {exp.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full border border-rule bg-paper px-3 py-1 text-xs text-ink-soft"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
                    <Button
                      onClick={() => navigate("/plan")}
                      className="bg-primary text-primary-foreground hover:bg-primary/90"
                    >
                      View plan
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-ink"
                      >
                        <Copy className="h-4 w-4" />
                        Duplicate
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-ink"
                      >
                        <Download className="h-4 w-4" />
                        Export
                      </Button>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
};

export default Library;
