import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# Bound sub-agent fan-out process-wide (Claude Code reads these from the env when it spawns the
# Agent tool): no nesting, at most 4 concurrent sub-agents. Overridable via real env vars.
os.environ.setdefault("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "1")
os.environ.setdefault("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "4")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    assistant_name: str = "Kioku"          # 記憶 — "memory"
    anthropic_api_key: str = ""          # leave empty in subscription (MODE A) mode
    vault_path: str = "/vault"

    model_triage: str = "claude-haiku-4-5"
    model_work: str = "claude-sonnet-5"
    model_orchestrator: str = "claude-opus-4-8"
    model_hard: str = "claude-fable-5"    # on Pro credit: essentially never auto-used

    # Turn budgets are GENEROUS on purpose — the #1 cause of failures was a 6-turn cap killing
    # real work mid-run. Heavy/background work (organize, learn, project runs) needs room to finish.
    max_turns: int = 80                    # global hard cap; per-difficulty caps are in the orchestrator
    # Sub-agent fan-out: powerful for big parallel jobs, but multiplies tokens — so it's enabled only
    # for heavy intents and hard-capped in dollars per run by the SDK's max_budget_usd.
    subagents_enabled: bool = True
    subagent_budget_usd: float = 2.5       # hard spend cap on any run that may fan out
    max_output_tokens: int = 8192
    run_timeout_seconds: int = 1500        # celery hard kill safety net (must exceed background timeout)
    # Per-run wall clock inside run_agent. Interactive (chat) stays snappy so you're not left hanging;
    # background jobs get a long budget so a big task can actually complete instead of stalling.
    interactive_timeout_seconds: int = 240
    background_timeout_seconds: int = 1200  # 20 min for briefs/organize/learn/project runs
    preflight_context_tokens: int = 12000  # assumed per-turn input context for the ceiling

    # Local timezone for scheduled work (morning brief, alerts, weekly review). Celery beat
    # runs in UTC unless told otherwise — set this so 07:00 means 07:00 where the user is.
    timezone: str = "UTC"

    # --- retrieval / embeddings ---
    # backend: local (sentence-transformers) | openai (or compatible) | voyage | none (BM25-only)
    embedding_backend: str = "none"   # BM25-only to start; flip to openai/voyage/local later
    embedding_model: str = "intfloat/multilingual-e5-small"  # meaning depends on backend
    embedding_dim: int = 384                # MUST match the vector(N) column in schema.sql
    embedding_api_key: str = ""
    embedding_api_base: str = "https://api.openai.com/v1"     # any OpenAI-compatible endpoint
    chunk_chars: int = 1600                # ~400 tokens per chunk
    retrieval_k: int = 5                    # notes pre-injected into a run so it answers in one turn
    connectors_path: str = "connectors.yaml"

    # --- opportunity radar (job scouting) ---
    job_boards: str = "wellfound.com,indeed.com,linkedin.com,remoteok.com"
    job_fit_floor: int = 70                # only surface roles scoring >= this fit (0-100)

    # --- computer-use (Phase 4.7): sites Kioku may drive a browser on. Comma-separated domains.
    # Empty = the browser_task tool refuses everything (the safe default). The LOCAL runner enforces
    # its own allow-list too (KIOKU_BROWSER_ALLOWED_SITES) and is off unless KIOKU_BROWSER_ENABLED=1.
    browser_allowed_sites: str = ""

    # git-backed vault (portable truth on ephemeral hosts like Railway; syncs to devices)
    vault_git_remote: str = ""            # e.g. https://x-access-token:TOKEN@github.com/you/vault.git
    vault_git_branch: str = "main"
    # identity for the worker's vault commits (fresh containers have no global git config)
    git_author_name: str = "KiokuAssistantAI"
    git_author_email: str = "noreply@example.com"

    # --- Agent SDK monthly credit guard (Pro = ~$20; Max 5x = 100; Max 20x = 200) ---
    agent_sdk_monthly_credit_usd: float = 20.0
    budget_conserve_at: float = 0.70      # cap Opus/Fable -> Sonnet; pause non-essential pollers
    budget_haiku_at: float = 0.85         # force Haiku for everything
    budget_halt_at: float = 0.95          # refuse non-essential tasks entirely

    database_url: str = "postgresql://kioku:kioku@db:5432/kioku"
    redis_url: str = "redis://redis:6379/0"

    # Web command center: a single shared secret gates the dashboard + API. With no token set the API
    # FAILS CLOSED: only loopback clients (the in-process Telegram bot, a local CLI) get through, unless
    # allow_unauthenticated is explicitly on — for a throwaway local stack, never for a deployment.
    dashboard_token: str = ""
    allow_unauthenticated: bool = False

    telegram_bot_token: str = ""
    telegram_allowed_user_id: str = ""
    # Leave blank in production: the in-process Telegram bot + CLI derive it from $PORT
    # (http://localhost:$PORT). Only set it when the API is reached at a fixed URL/port.
    api_base_url: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_sample_rate: float = 1.0

    # --- poller connector credentials (headless; not interactive OAuth) ---
    sentry_auth_token: str = ""
    sentry_org: str = ""
    sentry_project: str = ""
    vercel_token: str = ""
    github_token: str = ""
    github_repos: str = ""                 # comma-separated owner/repo
    app_db_url: str = ""                   # Acme DB — use a READ-ONLY role
    app_db_queries: str = ""               # name:SQL;name:SQL  (SELECT-only, enforced)
    # bank: READ-ONLY. There is intentionally no transfer capability anywhere in the code.
    bank_api_base: str = ""
    bank_token: str = ""
    bank_allow_transfers: bool = False     # hard-off; even True does nothing (no transfer code exists)

    @property
    def resolved_api_base(self) -> str:
        """Where the in-process Telegram bot / CLI reach the FastAPI app. If API_BASE_URL
        isn't set, derive it from the port uvicorn actually binds ($PORT on Railway; 8000
        locally) — a hardcoded :8000 would break the bot whenever $PORT differs."""
        if self.api_base_url:
            return self.api_base_url
        return f"http://localhost:{os.environ.get('PORT', '8000')}"


settings = Settings()
