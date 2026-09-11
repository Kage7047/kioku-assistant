# Reference · Configuration (every setting)

All via env (`pydantic-settings`); defaults in `src/kioku/config.py`. Example in `.env.example`.

## Identity
| Var | Default | Notes |
|---|---|---|
| `ASSISTANT_NAME` | `Kioku` | 記憶 — "memory" |

## Auth (pick one mode)
| Var | Default | Notes |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | — | **MODE A** (recommended): subscription credit. From `claude setup-token`. |
| `ANTHROPIC_API_KEY` | `""` | **MODE B**: pay-as-you-go. If set, it **silently overrides** MODE A. Leave unset for subscription. |

## Models & caps
| Var | Default |
|---|---|
| `MODEL_TRIAGE` | `claude-haiku-4-5` |
| `MODEL_WORK` | `claude-sonnet-5` |
| `MODEL_ORCHESTRATOR` | `claude-opus-4-8` |
| `MODEL_HARD` | `claude-fable-5` (never auto on Pro credit) |
| `MAX_TURNS` | `12` |
| `MAX_OUTPUT_TOKENS` | `4096` |
| `RUN_TIMEOUT_SECONDS` | `600` |
| `PREFLIGHT_CONTEXT_TOKENS` | `12000` (assumed per-turn context for the ceiling estimate) |

## Budget guard
| Var | Default | Notes |
|---|---|---|
| `AGENT_SDK_MONTHLY_CREDIT_USD` | `20.0` | Pro credit; Max 5x=100, 20x=200 |
| `BUDGET_CONSERVE_AT` | `0.70` | Opus/Fable→Sonnet; pause non-essential pollers |
| `BUDGET_HAIKU_AT` | `0.85` | force Haiku |
| `BUDGET_HALT_AT` | `0.95` | refuse non-essential tasks |

## Retrieval / embeddings
| Var | Default | Notes |
|---|---|---|
| `EMBEDDING_BACKEND` | `none` | `none` (BM25-only) · `openai` · `voyage` · `local` |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | meaning depends on backend |
| `EMBEDDING_DIM` | `384` | **must equal** `vector(N)` in `schema.sql` |
| `EMBEDDING_API_KEY` | `""` | for hosted backends |
| `EMBEDDING_API_BASE` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint |
| `CHUNK_CHARS` | `1600` | ~400 tokens/chunk |

## Vault (git-backed)
| Var | Default | Notes |
|---|---|---|
| `VAULT_PATH` | `/vault` | worker-owned checkout |
| `VAULT_GIT_REMOTE` | `""` | `https://x-access-token:<PAT>@github.com/you/vault.git` — enables sync |
| `VAULT_GIT_BRANCH` | `main` | |
| `CONNECTORS_PATH` | `connectors.yaml` | declarative source registry |

## Infra
| Var | Default |
|---|---|
| `DATABASE_URL` | `postgresql://kioku:kioku@db:5432/kioku` |
| `REDIS_URL` | `redis://redis:6379/0` |

## Front door
| Var | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | from @BotFather (api service) |
| `TELEGRAM_ALLOWED_USER_ID` | `""` | your numeric id — locks the bot to you |
| `API_BASE_URL` | `""` | Telegram/CLI target. Blank → auto `http://localhost:$PORT` (leave unset on Railway; the in-process bot follows uvicorn's port). Set only for a fixed external URL. |

## Observability
| Var | Default | Notes |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | `""` | no-op if unset |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | |
| `LANGFUSE_SAMPLE_RATE` | `1.0` | lower to stay under the free 50k units/mo |
