# DisasterOps

A working implementation of the *DisasterOps: Intelligent Shelter
Coordination and Emergency Logistics System* specification, built for
the **VJAI Hackathon 2026**.

This is a full-stack app: a Python/Flask decision-engine backend and a
vanilla JS coordinator/volunteer web frontend, running on a seeded
five-shelter disaster-response scenario in Da Nang, Vietnam. Every
number the app shows — urgency scores, feasibility scores, utility
rankings — is computed live from the formulas in the spec, from the
seed data, not hard-coded.

## The AI Agent (spec section 173)

This is the part that was **missing from the first version of this
build** — a deterministic decision engine alone doesn't make this
"Agentic AI." It's now implemented as a real tool-calling loop:

```bash
# AI agent -- pick ONE provider (free options first; paid Anthropic later)
export LLM_PROVIDER=ollama                # free, local, no key (install ollama, `ollama pull llama3.1`)
# export GROQ_API_KEY=...                 # free tier, console.groq.com (auto-detected)
# export GEMINI_API_KEY=...               # free tier, aistudio.google.com (auto-detected)
# export OPENROUTER_API_KEY=...           # free ':free' models
# export ANTHROPIC_API_KEY=sk-ant-...     # paid, console.anthropic.com
cd backend && ./run_backend.sh
```

Then in the app, go to **Coordinator → AI Agent** and try "Shelter A
urgently needs water." You'll see the actual tool-call trace: the
agent calls `find_shelter_or_need`, then `calculate_urgency` or
`get_shelter_state`, then `generate_recommendation` — each one hitting
the exact same deterministic engine the dashboard uses — before
writing a plain-language summary grounded in those results.

**What it can't do, on purpose:** approve or dispatch anything. Spec
section 68 is explicit that "the AI itself must not have authority to
mark a plan as pre-authorized" — a human coordinator still has to
click Approve in the dashboard. The agent investigates and
recommends; it has no tool that mutates state.

**Important caveat:** the sandbox this was built in has no outbound
network access, so `backend/app/agent/llm_client.py`'s call to
`api.anthropic.com` was written against the current Messages API
tool-use contract but **could not be tested live**. Everything else
in the agent layer — the tool functions themselves, the schemas, the
orchestration loop's logic — is covered by
`tests/test_agent_tools.py` (10 tests, all passing, run against the
real seeded database). The one untested seam is the actual HTTP
round-trip. Run `python3 -m tests.agent_live_smoke_test` once with
your key before a live demo to be sure; if anything about the request
shape has drifted, that script will surface it clearly.

## Quickstart

Two terminals, no Docker, no npm install:

```bash
# Terminal 1 — backend (Flask + SQLite, auto-seeds on first run)
cd backend
./run_backend.sh          # -> http://localhost:5001

# Terminal 2 — frontend (static files, no build step)
cd frontend
./run_frontend.sh         # -> http://localhost:8080
```

Open **http://localhost:8080**. Pick any demo account from the login
screen (all use password `demo1234`) — a Coordinator account
(`coordinator@disasterops.local`) sees the full command dashboard; a
Volunteer account (`volunteer.a@disasterops.local`, etc.) sees their
own shelter's simple mobile-first screens.

If you only have Python 3 available: both scripts fall back gracefully
— `run_backend.sh` creates a `venv` and installs Flask + PyJWT (the
only two dependencies); `run_frontend.sh` is just `python -m
http.server`. If you have Node's `serve` or any other static server
handy, that works too — `frontend/` is plain HTML/CSS/JS.

To run the automated tests (they reset and reseed `disasterops.db`):
```bash
cd backend
python3 -m unittest tests.test_acceptance tests.test_agent_tools tests.test_regressions -v
```

Optional environment variables: `LLM_PROVIDER` (`anthropic|ollama|groq|gemini|openrouter|openai`; inferred from whichever key is set, else `ollama`), `*_API_KEY` / `*_MODEL` per provider, `DISASTEROPS_SEED=demo` (force the synthetic Da Nang-style seed; real GSI Fukuoka data in `data/` is the default), `ANTHROPIC_MODEL` (override the agent's model), `DISASTEROPS_JWT_SECRET`, `DISASTEROPS_HOST` (default `127.0.0.1`), `DISASTEROPS_DEBUG=1` (Flask debugger; local use only).

## Real-geography demo: Fukuoka City from GSI open data

`backend/app/seed_gsi.py` swaps the Da Nang scenario for five real Fukuoka City
shelters (one per ward) taken from the Geospatial Information Authority of Japan's
designated-shelter files (put them in `data/`, e.g. `data/40000_1/40000_1.csv` and
`data/40000_2/40000_2.csv`). Real: shelter names, addresses, coordinates and the
hazards each co-located evacuation site covers. **Not real:** the GSI files have no
capacity, stock or consumption data, so populations, inventories, warehouses,
vehicles, roads and the storm scenario are the same synthetic values as the Da Nang demo.

```bash
cd backend && python3 -m app.seed_gsi && ./run_backend.sh   # seeds, then serves it
python3 -m unittest tests.test_gsi_seed -v
```
Use of the data is subject to GSI's terms of use and usage notes (included in the download).

## The five-minute demo script

This walks the same story as the spec's own "Recommended Demo User
Flow" (section 183):

1. **Log in as Coordinator.** The Command Dashboard shows 5 shelters,
   a schematic map, and a live-computed Priority Needs queue —
   Northgate Civic Hall's power failure and Riverside's water shortage
   are at the top.
2. **Go to AI Agent and type "Shelter A urgently needs water."**
   Expand the tool-call trace to show the agent resolving the name,
   pulling shelter state, calculating urgency, and generating a
   recommendation — each one a real call into the same engine the
   dashboard uses, not an invented number.
3. **Click "View full reasoning & approve"** on that need from the
   Active Needs screen. This is the same recommendation the agent just
   found, now in the human-approval UI: urgency factor breakdown, the
   recommended plan with a "why this plan?" explanation, every
   alternative candidate considered, and their scores.
4. **Click Approve.** A mission is dispatched; inventory and vehicle
   state update immediately. Note that the agent itself never had a
   tool that could do this — only a human clicking Approve can.
5. **Go to Roads & Weather → "Simulate closure"** on a road segment
   serving a *different* shelter with a pending need. Watch the
   response: DisasterOps invalidates the stale recommendation, finds
   an alternate route through the shelter's secondary road, and
   produces a brand-new ranked recommendation automatically — spec
   section 175's "Event-Driven Replanning" happening in real time.
6. **Log in as a Volunteer** (e.g. `volunteer.a@disasterops.local`) to
   see the deliberately opposite interface: one shelter, huge buttons,
   an hourly report form, a critical-update button, and the delivery
   they just watched get approved, ready to confirm on arrival.
7. **Audit Log** (Coordinator → System) shows every step above as an
   append-only, versioned record.

## Architecture, mapped to the spec

| Spec section | What it maps to in this repo |
|---|---|
| §7–18 Urgency Calculation | `backend/app/decision/urgency.py` |
| §50–64 Feasibility Scoring | `backend/app/decision/feasibility.py` |
| §74–101 Candidate Generation | `backend/app/decision/candidates.py` (Patterns A/B/C/D/G) |
| §112–134 Utility & Ranking | `backend/app/decision/utility.py`, `ranking.py` |
| §173 Agent Orchestration Layer | `backend/app/agent/` — real tool-calling loop against Claude (see above; HTTP round-trip untested, tool layer fully tested) |
| §144.9 Configuration Source of Truth | `backend/app/config.py` — every coefficient lives here, once |
| §144 Normative Contracts (enums, `DecisionContext`, versioning) | `ranking.build_context()`, status enums throughout |
| §148–149 Auth & RBAC | `backend/app/auth.py` |
| §164 API Endpoint Map | `backend/app/routers/*.py` |
| §169 Database Tables | `backend/app/db.py` (SQLite schema) |
| §150–159 Volunteer/Coordinator UI | `frontend/js/pages/*.js` |
| §175 Event-Driven Replanning | `POST /api/roads/events` in `resource_routes.py` |
| §179 Audit Logging | `db.write_audit()`, called at every decision-relevant step |
| §182 Minimum Hackathon Implementation | This entire build targets exactly that feature list |
| §144.13 Minimum Acceptance Tests | `backend/tests/test_acceptance.py` — several implemented as real unit tests |

## Design decisions worth knowing about

**Visual identity.** The frontend's colors and type were sampled
directly from the project's own proposal PDF (`DisasterOps_Proposal_
Revised_FINAL__VE_.pdf`) rather than invented: deep forest green
`#143e31` (headers, primary buttons), a brighter accent green
`#147e52` (links, focus states), pale mint `#f1f7f4` (card/table
emphasis), and the same warm off-black `#2e3733` for body text —
pulled by sampling actual pixel values off the rendered PDF pages, not
eyeballed. Headings use `Lora` (a serif, matching the proposal's own
single-typeface serif setting); dense UI — tables, forms, badges —
stays in a sans (`IBM Plex Sans`) for legibility at small sizes, which
the source document didn't need to solve since it's not an
interactive dashboard. Urgency/feasibility/utility badge colors stay
semantically distinct (red/orange/amber for danger, green for "good
news") rather than following brand color where that would contradict
the meaning of the data.

The spec is candid that its own coefficients ("prototype engineering
assumptions") need future calibration against real SOPs — this build
inherits that spirit, and adds a few of its own, made necessary by the
environment this was built in (**no internet access** — no `pip
install fastapi`, no `npm install` anything):

- **Flask + SQLite instead of FastAPI/PostgreSQL.** The spec explicitly
  lists this as an acceptable substitution ("Python FastAPI or
  Node.js... SQLite is acceptable... the exact implementation stack
  may be changed by the development team"). Business logic is
  cleanly separated from Flask, so porting to FastAPI later mostly
  means rewriting the thin `routers/` layer.
- **Vanilla JS frontend, no bundler.** No Vite/webpack/React toolchain
  was installable offline. What's here is plain ES5/ES6 with a
  hash-router and template-literal rendering, organized into the same
  page/component shape the spec's "Frontend Component Map" (§161)
  describes. It runs with zero install step, which is arguably a
  feature for a hackathon demo on conference wifi.
- **Google Maps and Weather API are mocked**, exactly as the spec
  anticipates (§174 lists them as pluggable external services).
  `decision/routing.py` computes real Haversine distances between the
  seeded shelters/warehouses and a configured average speed; road
  passability comes from the app's own `road_segments` table instead
  of a live traffic feed.
- **One road segment per shelter, with a secondary fallback.** Real
  routing would intersect a polyline against many closures; this
  model binds one primary + one optional secondary segment to each
  shelter, which is enough to demonstrate genuine reroute-on-closure
  behavior (see the demo script above) without a mapping engine.
- **Vehicle capacity in "cargo-litres."** Resources come in wildly
  different units (millilitres, meal portions, blanket counts, hours
  of generator runtime); `config.CARGO_LITRES_PER_UNIT` is a rough
  physical-volume conversion so one fleet of vehicles can be compared
  across resource types. It's a modeling simplification, not a
  spec requirement.
- **Candidate Generation implements Patterns A, B, C, D, and G**
  (direct/alternate warehouse, cross-shelter transfer, delayed
  vehicle, partial stabilization) — the ones exercised by the spec's
  own recommended demo flow. Patterns E/F/H (multi-trip, split
  delivery, mission reassignment) are structurally supported by the
  `CandidatePlan` contract's pattern enum but not generated, matching
  spec §107.1's explicit "Not Required for Initial MVP" list.
- **Mission continuity (utility factor M) is always 1** in this build,
  because the candidate generator never reassigns a vehicle away from
  an active mission — there's nothing to disrupt yet. The formula
  (§121) is fully implemented so a future `REASSIGNMENT` candidate
  would plug in without changes.
- **A couple of "AI Agent" pieces are structural, not literal.** The
  Agent Orchestration Layer itself (§173) is now real — see the
  section above. What's still not wired in: the RAG/SOP knowledge base
  (§90) that would let the agent cite actual policy documents, and
  the offline/PWA behavior (§177). The agent explains recommendations
  in plain language grounded in tool outputs, but doesn't yet retrieve
  and cite specific SOP clauses the way §90 describes.

None of these are hidden — they're the honest translation of a
200-page logical spec into a runnable prototype under a same-day
build with a sandboxed, offline dev environment. The math (urgency,
feasibility, utility) that hackathon judges are most likely to check
against the spec is implemented exactly, not approximated.

## What the live engine actually reproduces from the spec

Running the seeded scenario reproduces the spec's own worked numbers
where the seed data matches its examples:

- Shelter A's water need uses the spec's own example numbers verbatim
  (§165/§166: 210,000 mL on hand, 80,000 mL/h consumption, 500,000 mL
  target) and the live `calculateUrgency()` computes a Time-To-Failure
  of **157.5 minutes** — the spec's own worked example says "158 min."
- The Utility Engine's Pareto-dominance filter and tie-breaking
  (§128–130) run for real: in testing, a "delayed vehicle" candidate
  (Pattern D) sometimes out-ranked an immediately-available one on
  *utility*, because it preserved more fleet flexibility for future
  emergencies — while still correctly scoring *lower* on feasibility.
  That's not a bug; it's the spec's central architectural claim
  ("the fastest plan is not necessarily the best system-wide plan,"
  §127) actually happening, unscripted.

## Project structure

```
backend/
  app/
    config.py          versioned coefficients (spec §144.9)
    db.py               SQLite schema + state versioning + audit log
    auth.py             JWT login, RBAC decorators
    seed.py             Da Nang demo scenario (5 shelters, 2 warehouses, 5 vehicles)
    main.py             Flask app entrypoint
    decision/
      urgency.py        Urgency Engine
      feasibility.py    Feasibility Engine
      candidates.py     Candidate Generator (Patterns A/B/C/D/G)
      utility.py        Utility Engine
      ranking.py        Decision Engine orchestration + Pareto/tie-break ranking
      routing.py        Mock Google-Maps-equivalent (Haversine + road state)
    routers/            Flask blueprints, one per spec API resource group
  tests/
    test_acceptance.py  Several of the spec's own §144.13 acceptance tests
    e2e_smoke.py         Full HTTP walk-through of the demo flow
  requirements.txt
  run_backend.sh
frontend/
  index.html
  css/styles.css        design tokens: dark "situation room" for coordinators,
                         bright/high-contrast for volunteers
  js/
    api.js, router.js, utils.js
    components/         layout shells, schematic SVG ops map
    pages/              one file per screen, matching spec §160's route list
  run_frontend.sh
```

## Known limitations / good next steps

- No real LLM/RAG integration yet (§90, §173) — the deterministic
  decision engine is complete and is exactly what those layers are
  meant to call as tools.
- No live Google Maps / Weather API keys wired in — `routing.py` and
  the seeded `weather_snapshots` table are the integration points.
- Offline/PWA behavior (§177) isn't implemented — the frontend assumes
  connectivity to the backend.
- Multi-trip, split-delivery, and mission-reassignment candidates
  (Patterns E/F/H) aren't generated yet (explicitly optional for MVP
  per §107.1).
