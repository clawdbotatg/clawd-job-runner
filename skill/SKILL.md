# openrouter-jobrunner Skill

## What It Does

Automatically selects the best OpenRouter model for any task and runs it. Searches the full 400+ model catalog in real-time — not a curated subset. Picks based on modality fit, budget, capabilities, and context needs.

## Setup

1. Copy `jobrunner.py` to `~/.openclaw/skills/openrouter-jobrunner/`
2. Copy this `SKILL.md` to `~/.openclaw/skills/openrouter-jobrunner/`
3. Set `OPENROUTER_API_KEY` in your environment

Or install from the repo:
```bash
git clone https://github.com/clawdbotatg/clawd-job-runner.git
cp clawd-job-runner/jobrunner.py ~/.openclaw/skills/openrouter-jobrunner/
cp clawd-job-runner/skill/SKILL.md ~/.openclaw/skills/openrouter-jobrunner/
```

## How To Use (As An Agent)

Import and use the `JobRunner` class:

```python
import sys
sys.path.insert(0, os.path.expanduser("~/.openclaw/skills/openrouter-jobrunner"))
from jobrunner import JobRunner

runner = JobRunner()  # reads OPENROUTER_API_KEY from env

# Simple text task — auto-selects best model
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")

# Find model without executing
model = runner.find_model(
    task="Generate a pixel art sprite sheet",
    output_modalities=["image"],
    max_input_cost=5.0,
)
print(f"Would use: {model.id}")

# Image analysis
result = runner.run(
    task="Describe what's happening in this image",
    image_url="https://example.com/photo.jpg",
    verbose=True,
)

# Video with reasoning preference
result = runner.run(
    task="Analyze this security footage for unusual activity",
    video_url="https://example.com/clip.mp4",
    prefer=["reasoning"],
    verbose=True,
)

# Cheapest possible
result = runner.run(
    task="Translate to French: Hello world",
    budget="free",
)

# Coding task, budget capped
result = runner.run(
    task="Write a Solidity ERC-20 token with 6 decimals",
    prefer=["coding"],
    max_input_cost=1.0,
)
```

## JobResult Fields

| Field | Type | Description |
|---|---|---|
| `content` | str | Text output from the model |
| `model` | str | Actual model ID used |
| `cost` | float | Estimated cost in USD |
| `tokens_in` | int | Input tokens used |
| `tokens_out` | int | Output tokens generated |
| `image_urls` | list | URLs for image outputs (if any) |

## Budget Modes

| Mode | Behavior |
|---|---|
| `free` | Only free models |
| `cheap` | Sort by lowest cost first |
| `best` | Sort by capability (most features, largest context) |
| `default` | Balanced — moderate cost, solid capability |

## Preference Boosts

| Preference | Effect |
|---|---|
| `coding` | Boosts models known for code (Qwen, DeepSeek, etc.) |
| `reasoning` | Boosts models with reasoning/thinking support |
| `fast` | Boosts high-throughput models |

## Notes

- API key via `OPENROUTER_API_KEY` env var or `api_key=` param
- Model catalog is cached per `JobRunner` instance (one fetch per session)
- Verbose output goes to stderr; result content goes to stdout (clean for piping)
- Image output models return URLs in `result.image_urls`
