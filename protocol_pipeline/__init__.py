"""Stage 2 + 3 — Protocol generation + Materials extraction pipeline.

Multi-agent design:
  1. Normalize protocols.io samples (DraftJS -> plaintext, language detect)
  2. Relevance filter agent (drops obviously-off-target sources)
  3. Architect agent (emits ordered ProtocolOutline of named procedures)
  4. Procedure-writer agents (parallel fan-out, one per procedure — context
     isolation defends against drift on long protocols)
  5. Materials roll-up agent (de-duplicates equipment/reagents across
     procedures, adds spec + purpose for equipment items)

Sources: until the protocols.io client lands on a teammate's branch, this
pipeline reads the static sample JSONs in `pipeline_output_samples/
protocols_io/`. Once the live client is in, the only thing that changes
is the `sources` module's loader.
"""
