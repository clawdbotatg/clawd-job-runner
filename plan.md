# clawd-job-runner — Plan

> Give it a job. It finds the best LLM. It runs it.

## What This Is

A CLI tool (bash + Python) that:
1. Takes any task description as input
2. Queries the full OpenRouter model catalog in real-time (400+ models)
3. Analyzes what the task needs (modalities, capabilities, budget)
4. Picks the optimal model
5. Executes it
6. Returns the result + metadata (model used, cost, tokens)

This is NOT like `openrouter/auto` (which routes across ~6 curated models). This searches the entire catalog and filters/ranks based on what the task actually requires.

---

## Repo

- GitHub: https://github.com/clawdbotatg/clawd-job-runner
- Owner: clawdbotatg
- License: MIT

---

## File Structure

```
clawd-job-runner/
├── plan.md              ← this file
├── README.md            ← user-facing docs
├── jobrunner.sh         ← CLI entry point (bash, parses args, orchestrates)
├── jobrunner.py         ← core logic (model discovery, ranking, execution)
├── requirements.txt     ← just `requests` (stdlib otherwise)
├── .env.example         ← OPENROUTER_API_KEY=sk-or-v1-...
└── skill/
    ├── SKILL.md         ← OpenClaw skill wrapper
    └── jobrunner.py     ← symlink or copy for skill usage
```

---

## Core Flow

```
Your Task
   │
   ▼
Task Analyzer        — detect required modalities, infer capabilities needed
   │
   ▼
Model Catalog        — GET /api/v1/models → live 400+ model list
   │
   ▼
Ranker               — filter by modality fit → apply budget/prefs → rank
   │
   ▼
Execute              — POST /api/v1/chat/completions with chosen model
   │
   ▼
Result               — output + metadata (model, cost, tokens)
```

---

## Task Analyzer Logic

Keyword/heuristic detection on the task string + flags:

| Signal | Detected How |
|---|---|
| Image input | `--image` flag or keywords: "this image", "photo", "picture" |
| Video input | `--video` flag or keywords: "this video", "footage", "clip" |
| Audio input | `--audio` flag or keywords: "this audio", "transcribe" |
| File input | `--file` flag |
| Image output | keywords: "generate image", "draw", "create image", "pixel art" |
| Coding | `--prefer coding` or keywords: "write code", "solidity", "script", "function" |
| Reasoning | `--prefer reasoning` or keywords: "analyze", "explain", "reason" |
| Long context | `--min-context N` or keywords: "codebase", "full document" |

---

## Model Ranking Algorithm

1. **Hard filter** — modality match (input + output modalities must be supported)
2. **Hard filter** — min context window (if specified)
3. **Hard filter** — max input cost (if `--max-input-cost` set)
4. **Hard filter** — free only (if `--budget free`)
5. **Soft score** — preference boosts (`--prefer coding/reasoning/fast`)
6. **Sort** — by budget mode:
   - `free`: free models first
   - `cheap`: lowest input price first
   - `best`: largest context + most features first
   - default: balance of capability and cost

---

## CLI Flags

| Flag | Effect |
|---|---|
| `--budget free` | Only free models |
| `--budget cheap` | Sort by lowest cost first |
| `--budget best` | Sort by capability |
| `--prefer coding` | Boost coding-oriented models |
| `--prefer reasoning` | Boost reasoning-capable models |
| `--prefer fast` | Boost high max_completion_tokens models |
| `--input-modality X` | Force input modality filter (text/image/video/audio/file) |
| `--output-modality X` | Force output modality filter (text/image/audio) |
| `--min-context N` | Minimum context window |
| `--max-input-cost N` | Max $/M input tokens |
| `--image URL` | Pass image to model |
| `--video URL` | Pass video to model |
| `--audio URL` | Pass audio to model |
| `--file PATH` | Pass file to model |
| `--dry-run` | Show selected model + reasoning, don't execute |
| `--verbose` | Show full model selection reasoning |
| `--json` | Output result as JSON |

---

## Python Module API

```python
from jobrunner import JobRunner

runner = JobRunner(api_key="sk-or-...")

# Find best model without executing
match = runner.find_model(
    task="Generate a pixel art sprite sheet",
    input_modalities=["text"],
    output_modalities=["image"],
    max_input_cost=5.0,
)

# Find and execute
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")
```

---

## OpenClaw Skill

Drop `skill/SKILL.md` + `jobrunner.py` into `~/.openclaw/skills/openrouter-jobrunner/` and any agent can:

```
"Use the openrouter-jobrunner skill to find the best model for analyzing this video and run it"
```

The skill wrapper exposes `find_model()` and `run()` for agents to call programmatically.

---

## Build Phases

### Phase 1 — Core Python module (`jobrunner.py`)
- [ ] `JobRunner` class
- [ ] `fetch_models()` — live OpenRouter catalog query
- [ ] `analyze_task()` — modality + capability detection
- [ ] `rank_models()` — filter + score + sort
- [ ] `execute()` — OpenRouter chat completions call
- [ ] `JobResult` dataclass (content, model, cost, tokens_in, tokens_out)

### Phase 2 — CLI wrapper (`jobrunner.sh` + argparse in `jobrunner.py`)
- [ ] Bash entry point (env loading, python call)
- [ ] Full flag parsing
- [ ] `--dry-run`, `--verbose`, `--json` output modes
- [ ] Media URL passing (image/video/audio)

### Phase 3 — OpenClaw Skill (`skill/SKILL.md`)
- [ ] SKILL.md with usage instructions
- [ ] Install instructions

### Phase 4 — Docs & Polish
- [ ] README.md with examples
- [ ] `.env.example`
- [ ] `requirements.txt`
- [ ] MIT LICENSE

---

## Open Questions

- **OpenRouter API key**: needs to be provided via env or `.env` file
- **Video/audio modality**: OpenRouter's `/api/v1/models` endpoint — need to verify exact field names for modality metadata (`architecture.input_modalities`? or similar)
- **Image generation**: output modality — verify which models support `image` output
- **Output modality execution**: for image-out models, response format differs (URL vs base64) — handle both

---

## Notes

- Keep it single-file Python where possible (stdlib + `requests` only)
- No framework bloat — this should be copy-pasteable
- Verbose output goes to stderr so stdout stays clean for piping
- The bash wrapper handles `.env` loading so Python doesn't need python-dotenv
