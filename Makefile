PROJECT_NAME=aiutami-backend

.PHONY: help build up up-detached down logs migrate createsuperuser shell test

help:
	@echo "Comandi disponibili:"
	@echo "  make build            - Build delle immagini Docker"
	@echo "  make up               - Avvia web + db + redis in foreground"
	@echo "  make up-detached      - Avvia web + db + redis in background"
	@echo "  make down             - Ferma e rimuove i container"
	@echo "  make logs             - Mostra i log del container web"
	@echo "  make migrate          - Esegue le migrazioni Django"
	@echo "  make createsuperuser  - Crea un superuser Django"
	@echo "  make shell            - Apre una shell Django nel container web"
	@echo "  make test             - Esegue i test Django nel container web"

build:
	docker compose build

up:
	docker compose up

up-detached:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f web

migrate:
	docker compose run --rm web python manage.py migrate

createsuperuser:
	docker compose run --rm web python manage.py createsuperuser

shell:
	docker compose run --rm web python manage.py shell

test:
	docker compose run --rm web python manage.py test