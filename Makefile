.PHONY: up down logs audit shell demo demo-down test eval
up:        ; docker compose up --build
down:      ; docker compose down
logs:      ; docker compose logs -f worker api telegram
audit:     ; curl -s -XPOST localhost:8000/tasks -H 'content-type: application/json' -d '{"kind":"vault_audit","input":"audit the vault"}'
shell:     ; docker compose exec api python

# No API key needed: the stub model quotes the sample vault (see docs/DEMO.md).
demo:
	docker compose -f docker-compose.demo.yml up --build -d --wait api worker
	@echo ""
	@echo "  Kioku demo is up:  http://localhost:8000   (token: demo)"
	@echo "  Try: \"what's blocking Jonas\"  ·  \"that retry bug\"  ·  /audit"
	@echo "  Stop with: make demo-down"
demo-down: ; docker compose -f docker-compose.demo.yml down -v

test:      ; docker compose -f docker-compose.test.yml up -d --wait && pytest --cov
eval:      ; python eval/run_eval.py
