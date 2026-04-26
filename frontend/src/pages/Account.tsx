import SiteHeader from "@/components/SiteHeader";

const STATS = [
  { label: "Experiments generated", value: 12 },
  { label: "Plans reviewed", value: 8 },
  { label: "Feedback submitted", value: 5 },
];

const Account = () => {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <SiteHeader />

      <main className="mx-auto max-w-3xl px-6 pb-24 pt-12 sm:px-10 sm:pt-16">
        <header className="mb-10">
          <p className="mb-2 text-sm uppercase tracking-[0.18em] text-muted-foreground">
            Workspace
          </p>
          <h1 className="font-serif-display text-5xl text-ink">Account</h1>
          <p className="mt-3 max-w-2xl text-base text-muted-foreground">
            Your profile and recent activity on Praxis.
          </p>
        </header>

        {/* Profile card */}
        <section className="mb-10 rounded-lg border border-rule bg-paper-raised p-7 shadow-sm">
          <div className="flex items-center gap-5">
            <div
              aria-hidden
              className="flex h-16 w-16 items-center justify-center rounded-full border border-rule bg-paper font-serif-display text-2xl text-ink"
            >
              R
            </div>
            <div>
              <h2 className="font-serif-card text-2xl text-ink">Researcher</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                researcher@praxis.lab
              </p>
            </div>
          </div>
        </section>

        {/* Activity */}
        <section className="mb-10">
          <h2 className="mb-4 font-serif-section text-2xl text-ink">Activity</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {STATS.map((stat) => (
              <div
                key={stat.label}
                className="rounded-lg border border-rule bg-paper-raised p-6 shadow-sm"
              >
                <p className="font-serif-display text-4xl text-ink">
                  {stat.value}
                </p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </section>

        <p className="font-serif-accent text-base text-ink-soft/80">
          Your feedback helps improve future experiment plans.
        </p>
      </main>
    </div>
  );
};

export default Account;
