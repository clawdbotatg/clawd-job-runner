# 🧠 clawd-job-runner

> Give it a job. It finds the best LLM. It runs it.

A single-file CLI tool that takes any task — generate an image, analyze a video, write code, summarize a PDF — queries the full OpenRouter model catalog in real-time, picks the optimal model based on what the task actually needs, and executes it. One command, zero model selection.

There are 400+ models on OpenRouter. You shouldn't have to know which one accepts video, which one is cheapest for code, or which one can do tool calling. Describe what you want done, and the jobrunner figures out the rest.

**This is different from OpenRouter's built-in `openrouter/auto`** — that routes across ~6 curated models. The jobrunner searches the entire catalog and picks based on:

- **Required modalities** (text, image, video, audio, file input → text, image, audio output)
- **Budget** (set a max $/million tokens, or let it optimize)
- **Capabilities** (tool calling, structured output, reasoning)
- **Context window** (need 100K+? 1M? filtered automatically)
- **Speed vs quality** (prefer free models? cheapest? biggest context?)

## Install

```bash
git clone https://github.com/clawdbotatg/clawd-job-runner.git
cd clawd-job-runner
pip install requests
export OPENROUTER_API_KEY="sk-or-..."
```

Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys).

Or create a `.env` file:
```
OPENROUTER_API_KEY=sk-or-v1-...
```

## Usage

```bash
# Text task — finds best text model
./jobrunner.sh "Write a bash script that monitors disk usage and sends alerts"

# Image analysis — finds a vision model
./jobrunner.sh "Describe what's in this image" --image https://example.com/photo.jpg

# Video analysis — finds a video-capable model
./jobrunner.sh "Summarize this video" --video https://example.com/clip.mp4

# Code generation — prefers coding models
./jobrunner.sh "Write a Solidity ERC-20 token with 6 decimals" --prefer coding

# Cheapest possible — free models first
./jobrunner.sh "Translate this to French: Hello world" --budget free

# Force a specific modality filter
./jobrunner.sh "Transcribe this audio" --input-modality audio

# Max budget: $1/M input tokens
./jobrunner.sh "Analyze this codebase for security issues" --max-input-cost 1.0

# See what model it would pick without running
./jobrunner.sh "Explain quantum computing" --dry-run

# Full verbose output
./jobrunner.sh "Analyze this security footage" --video ./footage.mp4 --prefer reasoning --verbose
```

## How It Works

```
┌─────────────────┐
│   Your Task     │  "Analyze this video for safety violations"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Task Analyzer  │  Detects: needs video input, text output
│                 │  Infers: reasoning helpful, long output
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Model Catalog  │  GET /api/v1/models → 400+ models
│  (live query)   │  Filter: input_modalities includes "video"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Ranker      │  Score by: modality fit → pricing → context
│                 │  Apply budget/preference constraints
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Execute      │  POST /api/v1/chat/completions
│                 │  model: "google/gemini-3.1-flash-image-preview"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Result      │  Output + metadata:
│                 │  "Used google/gemini-3.1-flash-lite-preview"
│                 │  "Cost: $0.0003 | Tokens: 847"
└─────────────────┘
```

## Flags

| Flag | Effect |
|---|---|
| `--budget free` | Only free models (pricing = "0") |
| `--budget cheap` | Sort by lowest cost first |
| `--budget best` | Sort by capability (largest context, most features) |
| `--prefer coding` | Boost models with "code" in name/description |
| `--prefer reasoning` | Boost models that support reasoning parameter |
| `--prefer fast` | Boost models with high max_completion_tokens |
| `--input-modality X` | Filter to models accepting X (text/image/video/audio/file) |
| `--output-modality X` | Filter to models outputting X (text/image/audio) |
| `--min-context N` | Minimum context window (e.g., 100000) |
| `--max-input-cost N` | Max $/M input tokens (e.g., 1.0) |
| `--image URL` | Pass image URL to model |
| `--video URL` | Pass video URL to model |
| `--audio URL` | Pass audio URL to model |
| `--file PATH` | Pass file path to model |
| `--dry-run` | Show selected model + reasoning, don't execute |
| `--verbose` | Show full model selection reasoning |
| `--json` | Output result as JSON |

## Example Output

```bash
$ ./jobrunner.sh "Analyze this security footage for unusual activity" \
    --video ./footage.mp4 --prefer reasoning --verbose

🔍 Task analysis:
   Input modalities: text, video
   Output modalities: text
   Preferences: reasoning
   Budget: default

📋 Catalog: 344 models loaded
   After modality filter: 28 models

🏆 Selected: google/gemini-3.1-flash-image-preview
   Modalities: image+text+video → text
   Cost: $0.50/M input | Context: 1,000,000
   Reasoning: ✓
   Runner-up: openrouter/healer-alpha (free, 128,000 ctx)

⚡ Executing with google/gemini-3.1-flash-image-preview...

[... analysis output ...]

💰 Cost: $0.000847 | Tokens: 2,391 in / 1,203 out | Model: google/gemini-3.1-flash-image-preview
```

## Files

| File | What it does |
|---|---|
| `jobrunner.sh` | Entry point — loads .env, calls python |
| `jobrunner.py` | Core logic — model discovery, ranking, execution |
| `requirements.txt` | Just `requests` (stdlib otherwise) |
| `skill/SKILL.md` | OpenClaw skill wrapper |

## Python API

```python
from jobrunner import JobRunner

runner = JobRunner(api_key="sk-or-...")

# Find best model without executing
match = runner.find_model(
    task="Generate a pixel art sprite sheet",
    output_modalities=["image"],
    max_input_cost=5.0,  # $/M tokens
)
print(f"Would use: {match.id} at ${match.input_cost_per_m:.2f}/M")

# Find and execute
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")

# Image analysis
result = runner.run(
    "Describe this image",
    image_url="https://example.com/photo.jpg",
    verbose=True,
)

# Budget-constrained coding task
result = runner.run(
    "Write a FastAPI server with JWT auth",
    prefer=["coding"],
    budget="cheap",
)
```

## OpenClaw Skill

Drop `skill/SKILL.md` + `jobrunner.py` into `~/.openclaw/skills/openrouter-jobrunner/` and any agent can use it:

```
"Use the openrouter-jobrunner skill to find the best model for analyzing this video and run it"
```

## Features

- **Full catalog** — searches all 400+ OpenRouter models, not a curated subset
- **Modality-aware** — actually checks if the model can handle your input type
- **Live pricing** — always uses current pricing from the API
- **Transparent** — tells you exactly which model it picked and why
- **Budget control** — from free to frontier, you set the ceiling
- **Zero config** — one API key, one command, done
- **Pipeable** — result to stdout, metadata to stderr

## License

MIT — do whatever you want with it.
