.PHONY: up down logs fmt audit shell
up:      ; docker compose up --build
down:    ; docker compose down
logs:    ; docker compose logs -f worker api telegram
audit:   ; curl -s -XPOST localhost:8000/tasks -H 'content-type: application/json' -d '{"kind":"vault_audit","input":"audit the vault"}'
shell:   ; docker compose exec api python
