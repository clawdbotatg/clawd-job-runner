# 🧠 clawd-job-runner

> Give it a job. It finds the best LLM. It runs it.

A single-file CLI tool that takes any task — generate an image, analyze a video, write code, summarize a PDF — queries the full OpenRouter model catalog in real-time, picks the optimal model based on what the task actually needs, and executes it. One command, zero model selection.

There are 400+ models on OpenRouter. You shouldn't have to know which one accepts video, which one is cheapest for code, or which one can do tool calling. Describe what you want done, and the jobrunner figures out the rest.

**This is different from OpenRouter's built-in `openrouter/auto`** — that routes across ~6 curated models. The jobrunner searches the entire catalog and picks based on:

- **Required modalities** (text, image, video, audio, file input → text, image, audio output)
- **Budget** (set a max $/million tokens, or let it optimize)
- **Capabilities** (tool calling, structured output, reasoning)
- **Context window** (need 100K+? 1M? filtered automatically)
- **Speed vs quality** (prefer free models? cheapest? best?)

## Install

```bash
git clone https://github.com/clawdbotatg/clawd-job-runner.git
cd clawd-job-runner
pip install requests
```

Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys), then set it:

```bash
export OPENROUTER_API_KEY="sk-or-..."
# Or drop it in a .env file in the repo dir:
echo "OPENROUTER_API_KEY=sk-or-..." > .env
```

**Make it a global command:**

```bash
# Add to your shell profile (~/.zshrc or ~/.bashrc):
export PATH="$HOME/bin:$PATH"
export OPENROUTER_API_KEY="sk-or-..."

# Symlink so you can call it from anywhere:
mkdir -p ~/bin
ln -sf "$(pwd)/jobrunner.sh" ~/bin/jobrunner
```

Then just:

```bash
jobrunner "do this thing"
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

# Force input modality
./jobrunner.sh "Transcribe this audio" --input-modality audio

# Cap cost at $1/M input tokens
./jobrunner.sh "Analyze this codebase for security issues" --max-input-cost 1.0

# See what model it would pick without running
./jobrunner.sh "Explain quantum computing" --dry-run --verbose
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
│                 │  Infers: reasoning helpful
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
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Result      │  Output + metadata (model, cost, tokens)
└─────────────────┘
```

## Flags

| Flag | Effect |
|---|---|
| `--budget free` | Only free models |
| `--budget cheap` | Sort by lowest cost first |
| `--budget best` | Sort by capability (largest context, most features) |
| `--prefer coding` | Boost coding-oriented models |
| `--prefer reasoning` | Boost models with reasoning/thinking support |
| `--prefer fast` | Boost high-throughput models |
| `--input-modality X` | Filter to models accepting X (text/image/video/audio/file) |
| `--output-modality X` | Filter to models outputting X (text/image/audio) |
| `--min-context N` | Minimum context window (e.g., `100000`) |
| `--max-input-cost N` | Max $/M input tokens (e.g., `1.0`) |
| `--image URL` | Pass image URL to model |
| `--video URL` | Pass video URL to model |
| `--audio URL` | Pass audio URL to model |
| `--file PATH` | Pass file to model |
| `--dry-run` | Show selected model, don't execute |
| `--verbose` | Show full model selection reasoning |
| `--json` | Output result as JSON |

## Example Output

```
$ ./jobrunner.sh "Analyze this security footage for unusual activity" \
    --video ./footage.mp4 --prefer reasoning --verbose

📋 Task Analysis:
   Input:  text, video
   Output: text
🔍 Fetching OpenRouter model catalog...
📦 Found 344 models

🏆 Top 5 matches:
   👉 1. Google: Gemini 3.1 Flash Lite Preview
        google/gemini-3.1-flash-lite-preview | ctx: 1,048,576 | $0.25/M
      2. Google: Gemini 3.1 Pro Preview
        google/gemini-3.1-pro-preview | ctx: 1,048,576 | $2.00/M
      ...

✅ Selected: Google: Gemini 3.1 Flash Lite Preview
🚀 Executing...

[... analysis output ...]

💰 Cost: $0.000847 | Tokens: 2,391 in / 1,203 out
```

## Python API

```python
from jobrunner import JobRunner

runner = JobRunner(api_key="sk-or-...")

# Find best model without executing
match = runner.find_model(
    task="Generate a pixel art sprite sheet",
    output_modalities=["image"],
    max_input_cost=5.0,
)
print(f"Would use: {match.id}")

# Find and execute
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")

# With media
result = runner.run(
    "Describe what's in this image",
    image_url="https://example.com/photo.jpg",
    verbose=True,
)

# Budget-constrained coding
result = runner.run(
    "Write a FastAPI server with JWT auth",
    prefer=["coding"],
    budget="cheap",
)
```

## Files

| File | What it does |
|---|---|
| `jobrunner.sh` | Entry point — loads `.env`, calls Python |
| `jobrunner.py` | Core logic — model discovery, ranking, execution |
| `requirements.txt` | Just `requests` (stdlib otherwise) |

## Features

- **Full catalog** — searches all 400+ OpenRouter models, not a curated subset
- **Modality-aware** — actually checks if the model can handle your input type
- **Live pricing** — always uses current pricing from the API
- **Transparent** — shows exactly which model it picked and why
- **Budget control** — from free to frontier, you set the ceiling
- **Zero config** — one API key, one command, done
- **Pipeable** — result to stdout, metadata to stderr

## License

MIT
