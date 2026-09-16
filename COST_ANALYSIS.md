# LLM Cost Analysis

The application reports actual Gemini usage from the API response. It does not fabricate token counts or costs.

## Configuration

Set these values in `.env` before running the application:

```dotenv
GEMINI_API_KEY=
LLM_PROVIDER=
LLM_MODEL=
LLM_INPUT_COST_PER_1M_TOKENS=
LLM_OUTPUT_COST_PER_1M_TOKENS=
```

Use the same variables for any supported provider integration. `LLM_INPUT_COST_PER_1M_TOKENS` and `LLM_OUTPUT_COST_PER_1M_TOKENS` must contain the provider/model prices in USD per one million tokens.

## Calculation

For each fallback call:

```text
input cost = input tokens / 1,000,000 * input price for gemini is 0.30$
output cost = output tokens / 1,000,000 * output price for for gemini is 2.50$
total cost = input cost + output cost
```

The CLI aggregates these values for each document and displays an estimate for 1,000 documents by multiplying the observed document cost by 1,000.

## Provider Comparison

| Provider | Configuration | Input price | Output price | Notes |
|---|---|---:|---:|---|
| Google Gemini | `LLM_PROVIDER=Google` | Set in `.env` | Set in `.env` | Current `llm.py` integration; receives only relevant extracted context. |
| OpenAI | `LLM_PROVIDER=OpenAI` | Set from the selected model's pricing | Set from the selected model's pricing | Requires a provider-specific client implementation before use. |
| Anthropic | `LLM_PROVIDER=Anthropic` | Set from the selected model's pricing | Set from the selected model's pricing | Requires a provider-specific client implementation before use. |

The current implementation supports the existing Google Gemini integration only. The comparison table documents the same cost interface for future provider configuration without claiming that those providers are already implemented.

## Run Instructions

Before running, copy `.env.example` to `.env`, fill in the API key and model settings, and use the provider's current published token prices:

```powershell
Copy-Item .env.example .env
python app.py 2022-annual.pdf --table
python app.py 2022-annual.pdf icici-bank-2026-financial-statements.pdf --table
```

Never commit `.env` or share `GEMINI_API_KEY`.
