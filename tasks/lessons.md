# Lessons

Failure modes discovered, the signal that caught them, and the prevention rule.

---

## L1 — Verify API tier/season access on the REAL key before building on it (2026-06-05)
- **Failure mode:** DESIGN.md assumed API-Football (free tier) as the data workhorse and its
  integer IDs as canonical, across the whole schema. The free plan in fact only serves seasons
  **2022–2024** — it cannot read the 2026 World Cup at all (`"Free plans do not have access to
  this season"`). Building the ingestion layer on that assumption would have been dead on arrival.
- **Detection signal:** a single live probe `GET /leagues?id=1&season=2026` returned
  `results: 0` with a plan-gate error — caught before any adapter code existed.
- **Prevention rule:** before designing on top of an external API, probe the *actual key* for the
  *actual resource* you need (right season/endpoint/plan), not just "does the key auth." Treat
  vendor docs' free-tier claims as unverified until the key proves it. DESIGN §10 even flagged
  this as risk A4 — honor day-1 verification risks early, not at cutover.

## L2 — Don't hardcode a data source's IDs as your canonical key (2026-06-05)
- **Failure mode:** "Canonical IDs are API-Football's integers — no ID mapping" was baked into
  models, db, and CLAUDE.md. When the source changed (to openfootball, which has names only), that
  invariant had to be torn out of multiple layers.
- **Prevention rule:** anchor canonical identity on a source-independent natural key (here: the
  normalized team name) and treat integer ids as locally-minted surrogates. Keep the source
  adapter as the only place that knows the vendor's id scheme.

## L3 — Parse LLM section markers tolerantly; models glue text onto headers (2026-06-05)
- **Failure mode:** the dossier parser anchored section headers to line start (`^### BASELINE$`).
  The intelligence model emitted a preamble glued onto the first header
  (`"...national team.### BASELINE\n..."`), so the line-anchored regex missed BASELINE and the
  build failed loud. Same glue bug then recurred in `_strip_preamble`'s heading detector.
- **Detection signal:** `LLMError: dossier ... missing/empty sections ['BASELINE']` on the first
  real run, with the raw output showing the header mid-line.
- **Prevention rule:** when parsing structure out of LLM prose, match on the strong markdown signal
  (`#{1,4}\s+`) ANYWHERE, not anchored to line start; use an end-of-line lookahead to avoid matching
  the header words inside sentences. Pair a firm "output only the content, no narration" instruction
  with a defensive post-strip — instructions reduce the noise, the parser must still tolerate it.

## L5 — Read the ACTIVE config (.env overrides), not the code default (2026-06-05)
- **Failure mode:** told the user the intelligence runs used the free model because `config.py`
  had `use_free_models: bool = True` as the default. The `.env` actually set `USE_FREE_MODELS=false`,
  so the PREMIUM lineup (Opus 4.8 intelligence) ran — confirmed when a `GET /generation?id=` lookup
  reported `model='anthropic/claude-4.8-opus'`. The wrong claim sent the cost analysis off-track.
- **Detection signal:** user said their OpenRouter dashboard showed Opus 4.8 usage, contradicting my
  "free model" claim. The generation-id lookup settled it against ground truth.
- **Prevention rule:** when reporting which model/config is in effect, evaluate the *resolved* value
  (`settings.x`, the generation's reported `model`), never the literal default in the class. For LLM
  cost questions, the per-generation `/generation` endpoint and the logged `generation_id` are the
  source of truth — use them before extrapolating.

## L4 — OpenRouter web search needs a funded balance; verify before building (2026-06-05)
- **Context:** the intelligence agent gets facts via OpenRouter's `web` plugin (server-side search
  injected into the prompt), not a pydantic-ai tool loop — smallest change that fits `llm.py`.
- **Prevention rule (echoes L1):** the `web` plugin is a paid feature; before building on it, probe
  `GET /api/v1/key` for `is_free_tier`/`limit`. Here the key was funded (`is_free_tier:false`), so it
  works. On a $0 free-tier key it would silently degrade — check the capability on the real key first.

## L6 — Compute the test fixture from the rule it exercises, not a round number (2026-06-06)
- **Failure mode:** the settlement regression set the bust-case bankroll to $15k expecting a capped
  loss to cross the $10k floor — but the 25% cap means the max loss is $3.75k, so $15k→$11.25k never
  busted and the re-buy assertion failed. The starting figure was picked for being "near the floor"
  rather than derived from the cap × floor interaction.
- **Detection signal:** `AssertionError ... bankroll=11250.0 lives_used=0` on first run — the test
  caught its own bad setup, not a code bug.
- **Prevention rule:** when a test must trigger a threshold crossing, derive the input from the
  mechanic (here: need `bankroll*(1-0.25) <= floor` ⇒ `bankroll <= 13_333`), don't eyeball a
  "looks close enough" constant. A test whose fixture isn't computed from the rule can pass or fail
  for the wrong reason.
