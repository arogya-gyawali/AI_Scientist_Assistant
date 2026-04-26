import { useEffect, useRef, useState } from "react";
import { Check, Send, Sparkles, X } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  dispatchChatApplied,
  getActivePlanId,
  postChat,
  postChatApply,
  type ChatMessage,
  type ProposedMutation,
} from "@/lib/api";

// ----------------------------------------------------------------------------
// AI Assistant — propose-then-apply chat over the experiment-plan blackboard.
//
// On send, we POST /chat with the current plan_id (from sessionStorage —
// pages register it via setActivePlanId), the route the user is on, and the
// conversation history. The backend may return zero or more proposed
// mutations alongside the assistant's prose reply; we render those as cards
// with Apply / Reject buttons. Apply round-trips the mutation back to
// /chat/apply, then dispatches a `praxis:chat-applied` event so the host
// page can refresh the affected sections in place from the BE-rendered
// frontend_views the apply endpoint returns.
//
// Read-only routes (e.g. `/lab` before there's a plan) just answer questions
// — the backend exposes no mutator tools there, so `proposed_mutations` is
// always empty.
// ----------------------------------------------------------------------------

type LocalMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  // Only on assistant turns: proposals attached to this reply.
  proposals?: ProposedMutation[];
  // Per-proposal applied / rejected ids so the buttons disable + the card
  // reflects state without having to mutate the proposals[] in place.
  appliedIds?: Set<string>;
  rejectedIds?: Set<string>;
  applyError?: string;  // shown if /chat/apply itself fails
};

type RouteContext = {
  label: string;
  subtitle: string;
  suggestions: string[];
};

const ROUTE_CONTEXT: Record<string, RouteContext> = {
  "/": {
    label: "Welcome",
    subtitle: "Ask how Praxis works",
    suggestions: [
      "What can Praxis help me do?",
      "How does the workflow work?",
      "What kind of hypotheses work best?",
    ],
  },
  "/lab": {
    label: "Hypothesis",
    subtitle: "Ask about framing your hypothesis",
    suggestions: [
      "How do I write a testable hypothesis?",
      "What makes a hypothesis too vague?",
      "Suggest a variable to control.",
    ],
  },
  "/literature": {
    label: "Literature",
    subtitle: "Ask about prior work and novelty",
    suggestions: [
      "Summarize the most relevant paper.",
      "Is this hypothesis novel?",
      "What gaps exist in the literature?",
    ],
  },
  "/plan": {
    label: "Experiment plan",
    subtitle: "Ask about the protocol or propose an edit",
    suggestions: [
      "Make step p1-s1 a critical step.",
      "Add 1 L of PBS to materials.",
      "Set step p1-s3 duration to 15 minutes.",
    ],
  },
  "/account": {
    label: "Account",
    subtitle: "Ask about your activity",
    suggestions: [
      "How many experiments have I generated?",
      "What's my most-used organism?",
    ],
  },
};

const DEFAULT_CONTEXT: RouteContext = {
  label: "Praxis",
  subtitle: "Ask anything about your work",
  suggestions: [
    "What can you help me with?",
    "Summarize what I'm looking at.",
  ],
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  route?: string;
};

export const AIAssistantPanel = ({ open, onOpenChange, route = "/" }: Props) => {
  // ctx still drives the panel header label + subtitle; the suggestions
  // panel was removed because the canned questions seeded "lowest-common-
  // denominator" prompts that pushed users toward generic answers. Empty
  // chat-state is the better blank-canvas affordance.
  const ctx = ROUTE_CONTEXT[route] ?? DEFAULT_CONTEXT;

  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pending]);

  // Build the wire-format history the backend expects: prior turns only,
  // text content only (proposals are server-state — we don't replay them).
  const buildHistory = (msgs: LocalMessage[]): ChatMessage[] =>
    msgs.map((m) => ({ role: m.role, content: m.content }));

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;

    const planId = getActivePlanId();
    const userMsg: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");

    if (!planId) {
      // No plan loaded — surface a clear stub rather than calling the BE
      // (which would 400 anyway). This shows up on /lab before a hypothesis
      // is submitted, or on routes that don't carry a plan.
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "No plan is loaded yet. Submit a hypothesis on the Lab page to start one — I can then answer questions and propose edits against it.",
        },
      ]);
      return;
    }

    setPending(true);
    try {
      const historyForApi = buildHistory(
        messages.filter((m) => !m.applyError).slice(-12),
      );
      const res = await postChat({
        plan_id: planId,
        page: route,
        message: trimmed,
        history: historyForApi,
      });
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: res.message,
          proposals: res.proposed_mutations.length ? res.proposed_mutations : undefined,
        },
      ]);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Chat request failed.";
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `(error) ${detail}`,
        },
      ]);
    } finally {
      setPending(false);
    }
  };

  // Apply one proposal: round-trip it back to /chat/apply, dispatch the
  // applied event so the host page refreshes its sections, then mark it
  // applied locally so the button flips to a check.
  const applyProposal = async (assistantMsgId: string, proposal: ProposedMutation) => {
    const planId = getActivePlanId();
    if (!planId) return;
    try {
      const res = await postChatApply({ plan_id: planId, mutations: [proposal] });
      // Tell the host page to refresh its affected sections from the
      // updated frontend_views the apply endpoint returned.
      dispatchChatApplied({ plan_id: res.plan_id, frontend_views: res.frontend_views });
      const wasApplied = res.applied_ids.includes(proposal.id);
      const errorEntry = res.errors.find((e) => e.mutation_id === proposal.id);
      setMessages((msgs) =>
        msgs.map((m) => {
          if (m.id !== assistantMsgId) return m;
          if (wasApplied) {
            const next = new Set(m.appliedIds ?? []);
            next.add(proposal.id);
            return { ...m, appliedIds: next };
          }
          return {
            ...m,
            applyError: errorEntry?.error ?? "Apply failed.",
          };
        }),
      );
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Apply request failed.";
      setMessages((msgs) =>
        msgs.map((m) => (m.id === assistantMsgId ? { ...m, applyError: detail } : m)),
      );
    }
  };

  const rejectProposal = (assistantMsgId: string, proposalId: string) => {
    setMessages((msgs) =>
      msgs.map((m) => {
        if (m.id !== assistantMsgId) return m;
        const next = new Set(m.rejectedIds ?? []);
        next.add(proposalId);
        return { ...m, rejectedIds: next };
      }),
    );
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 border-l border-rule bg-paper p-0 sm:max-w-[440px]"
      >
        {/* Header */}
        <SheetHeader className="space-y-2 border-b border-rule bg-paper-raised px-6 py-5 text-left">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-sm border border-rule bg-paper"
            >
              <Sparkles className="h-3.5 w-3.5 text-primary" strokeWidth={1.75} />
            </span>
            <SheetTitle className="font-serif-display text-[22px] text-ink">
              AI Assistant
            </SheetTitle>
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-sm border border-rule bg-paper px-2 py-1 font-mono-notebook text-[10px] uppercase tracking-[0.2em] text-ink-soft">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-sage" />
              {ctx.label}
            </span>
          </div>
          <SheetDescription
            className="text-[14px] italic text-ink-soft"
            style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
          >
            {ctx.subtitle}
          </SheetDescription>
        </SheetHeader>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-5">
          {messages.length === 0 && (
            <p
              className="text-center text-[14px] italic text-muted-foreground"
              style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
            >
              Pick a suggestion or type a question to begin.
            </p>
          )}
          <div className="flex flex-col gap-4">
            {messages.map((m) => (
              <div
                key={m.id}
                className={cn(
                  "flex flex-col",
                  m.role === "user" ? "items-end" : "items-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[85%] rounded-md px-3.5 py-2.5 text-[14.5px] leading-[1.55]",
                    m.role === "user"
                      ? "bg-ink text-paper"
                      : "border border-rule bg-paper-raised text-ink-soft",
                  )}
                >
                  {m.role === "assistant" && (
                    <p className="mb-1.5 font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                      Assistant
                    </p>
                  )}
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>

                {/* Proposed mutations — only on assistant turns */}
                {m.role === "assistant" && m.proposals && m.proposals.length > 0 && (
                  <div className="mt-2.5 flex w-full max-w-[85%] flex-col gap-2">
                    {m.proposals.map((p) => {
                      const applied = m.appliedIds?.has(p.id);
                      const rejected = m.rejectedIds?.has(p.id);
                      const settled = applied || rejected;
                      return (
                        <div
                          key={p.id}
                          className={cn(
                            "relative overflow-hidden rounded-md border bg-paper-raised px-3.5 py-3 text-[13px] transition-colors",
                            applied
                              ? "border-sage/40"
                              : rejected
                                ? "border-rule/60 opacity-60"
                                : "border-primary/30",
                          )}
                        >
                          <span
                            aria-hidden
                            className={cn(
                              "absolute inset-y-0 left-0 w-[2px]",
                              applied ? "bg-sage" : rejected ? "bg-rule" : "bg-primary",
                            )}
                          />
                          <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                            Proposed change
                          </p>
                          <p className="mt-1 leading-[1.5] text-ink">{p.summary}</p>
                          {!settled && (
                            <div className="mt-2.5 flex gap-2">
                              <Button
                                type="button"
                                size="sm"
                                onClick={() => applyProposal(m.id, p)}
                                className="h-7 gap-1.5 rounded-sm bg-ink px-3 text-[11px] font-mono-notebook uppercase tracking-[0.22em] text-paper hover:bg-ink/90"
                              >
                                <Check className="h-3 w-3" strokeWidth={2.25} />
                                Apply
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={() => rejectProposal(m.id, p.id)}
                                className="h-7 gap-1.5 rounded-sm border-rule bg-paper px-3 text-[11px] font-mono-notebook uppercase tracking-[0.22em] text-ink-soft hover:bg-rule-soft/40"
                              >
                                <X className="h-3 w-3" strokeWidth={2.25} />
                                Reject
                              </Button>
                            </div>
                          )}
                          {applied && (
                            <p className="mt-2 inline-flex items-center gap-1.5 font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-sage">
                              <Check className="h-3 w-3" strokeWidth={2.25} />
                              Applied
                            </p>
                          )}
                          {rejected && (
                            <p className="mt-2 inline-flex items-center gap-1.5 font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                              Rejected
                            </p>
                          )}
                        </div>
                      );
                    })}
                    {m.applyError && (
                      <p
                        role="alert"
                        className="rounded-sm border border-destructive/30 bg-paper px-3 py-2 font-mono-notebook text-[11px] uppercase tracking-[0.22em] text-destructive"
                      >
                        {m.applyError}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
            {pending && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-md border border-rule bg-paper-raised px-3.5 py-2.5">
                  <p className="font-mono-notebook text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                    Assistant
                  </p>
                  <p className="mt-1.5 flex items-center gap-2 text-[14.5px] italic text-ink-soft">
                    <span className="flex gap-1">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-soft/60 [animation-delay:0ms]" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-soft/60 [animation-delay:150ms]" />
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-soft/60 [animation-delay:300ms]" />
                    </span>
                    Thinking…
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Input */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="border-t border-rule bg-paper-raised px-4 py-4"
        >
          <div className="flex items-end gap-2 rounded-md border border-rule bg-paper px-3 py-2 focus-within:border-ink/40">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder="Ask about the plan, or propose an edit…"
              className="max-h-32 flex-1 resize-none bg-transparent py-1.5 text-[14.5px] leading-[1.5] text-ink placeholder:text-muted-foreground focus:outline-none"
            />
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim() || pending}
              className="h-8 w-8 shrink-0 rounded-sm bg-ink text-paper hover:bg-ink/90 disabled:opacity-40"
              aria-label="Send"
            >
              <Send className="h-3.5 w-3.5" strokeWidth={2} />
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
};

export default AIAssistantPanel;
