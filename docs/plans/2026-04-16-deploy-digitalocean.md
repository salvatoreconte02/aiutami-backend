# Deploy produzione — DigitalOcean + dominio `.me`

**Data:** 2026-04-16
**Autore:** Salvatore + Claude
**Contesto:** La migrazione Azure → OpenAI è completata e tutti i servizi AI
sono operativi (LLM gpt-4o-mini, STT gpt-4o-mini-transcribe via Realtime API,
TTS gpt-4o-mini-tts). Manca solo il deploy su un server pubblico per poter
testare le sessioni multi-partecipante end-to-end e condurre la valutazione
empirica NASA Moon Survival. Deploy "tutto-in-uno": backend + frontend sullo
stesso VPS, un solo dominio HTTPS.

---

## 1. Scope

- Registrare dominio `.me` gratuito via GitHub Student Pack (Namecheap)
- Creare droplet DigitalOcean usando credito Student Pack ($200 / 12 mesi)
- Configurare server: Docker, Nginx reverse proxy, HTTPS Let's Encrypt
- Deploy backend Django+Daphne via docker-compose (repo attuale)
- Build + deploy frontend React+Vite come static files servite da Nginx
- Test end-to-end con 2+ partecipanti
- (Opzionale, fase 2) Coturn se emergono problemi NAT

## 2. Decisioni prese

| Topic | Scelta | Motivazione |
|---|---|---|
| Registrar | Namecheap (via Student Pack) | `.me` gratis 1 anno |
| Dominio | `aiutami-polimi.me` | Registrato 2026-04-16 |
| Cloud | DigitalOcean | $200 credito Student Pack |
| Droplet | Basic 4GB / 2 vCPU / 80GB SSD | ~$24/mese, regge 3-6 partecipanti |
| Region | Frankfurt (FRA1) | Latenza minima dall'Italia |
| OS | Ubuntu 24.04 LTS | Standard, Docker compat |
| Deploy frontend | Static serviti da Nginx | Stesso dominio, no CORS |
| TURN server | No (fase 1), eventuale coturn in fase 2 | Server ha IP pubblico, STUN basta in ~95% casi |
| SSH key | `~/.ssh/id_ed25519` (Ed25519, no passphrase) | Generata 2026-04-16 |

## 3. Architettura target

```
 Browser partecipante
        │
        │ HTTPS (443) + WSS (443)
        ▼
  ┌─────────────────────┐
  │      Nginx          │
  │  (host, non docker) │ ── /         → static dist/ (frontend)
  │                     │ ── /api/     → proxy → Daphne :8000
  │                     │ ── /ws/      → proxy WS → Daphne :8000
  │                     │ ── /admin/   → proxy → Daphne :8000
  └─────────┬───────────┘
            │
            ▼  (internal, docker network)
  ┌──────────────────────────────┐
  │ docker compose:              │
  │  - web (Django+Daphne :8000) │
  │  - postgres (:5432)          │
  │  - redis (:6379)             │
  └──────────────────────────────┘

  UDP 10000-10050 ─────→ aiortc (dentro container web, port exposed)
```

## 4. TODO — Step by step

### Fase A: preparazione (prima di creare il server)

- [x] A1. Generare chiave SSH locale (`~/.ssh/id_ed25519`)
- [x] A2. Verificare GitHub Student Pack su `education.github.com/pack`
- [x] A3. Riscattare benefit **Namecheap** (1 anno `.me` gratis)
- [x] A4. Registrare `aiutami-polimi.me`
- [x] A5. Riscattare benefit **DigitalOcean** ($200 credito)

### Fase B: provisioning server

- [x] B1. Creare droplet DigitalOcean (Basic 4GB, Ubuntu 24.04, Frankfurt)
- [x] B2. Durante creazione: incollare chiave pubblica `~/.ssh/id_ed25519.pub`
- [x] B3. Salvare IP pubblico del droplet — **`209.38.194.166`**
- [x] B4. Configurare DNS Namecheap: A record `aiutami-polimi.me` → `209.38.194.166`
- [x] B5. Verificare risoluzione DNS (`dig aiutami-polimi.me` da locale) ✅ propagato

### Fase C: hardening server

- [x] C1. Creato utente `salvatore_aiutami` con home e gruppo sudo
- [x] C2. Copiata chiave SSH pubblica su `salvatore_aiutami`, login verificato
- [x] C3. Disabilitato login root SSH + password auth (`sshd_config`)
- [x] C4. UFW attivo: `22/tcp`, `80/tcp`, `443/tcp`, `10000-10050/udp`
- [x] C5. fail2ban attivo con jail SSH (5 tentativi → ban 1h)
- [x] C6. Timezone `Europe/Rome`, unattended-upgrades attivo

### Fase D: runtime (Docker + app)

- [x] D1. Docker Engine + Compose plugin installati
- [x] D2. Repo clonata in `/home/salvatore_aiutami/aiutami-backend`
- [x] D3. `.env` produzione creato (DEBUG=0, ALLOWED_HOSTS, OPENAI_API_KEY, Postgres password sicura)
- [x] D4. `docker compose -f docker-compose.prod.yml up -d` — web, postgres, redis UP
- [x] D5. Migrazioni applicate (tutte le app)
- [x] D6. Superuser Django creato (admin / admin@aiutami-polimi.me)
- [x] D7. Collectstatic completato (154 file, già inclusi nel Dockerfile.prod)

### Fase E: Nginx + HTTPS

- [x] E1. Nginx installato sull'host
- [x] E2. Reverse proxy configurato (`/api/`, `/admin/`, `/ws/` con WS upgrade, `/static/`)
- [x] E3. Certbot installato (snap)
- [x] E4. Certificato Let's Encrypt ottenuto (scade 2026-07-19, auto-renewal attivo)
- [x] E5. Auto-renewal verificato (`certbot renew --dry-run` OK)

### Fase F: frontend

- [x] F1. Build con `VITE_API_URL=https://aiutami-polimi.me` e `VITE_WS_URL=wss://aiutami-polimi.me`
- [x] F2. `npm run build` → `dist/` (7 file, 302 KB, PWA con service worker)
- [x] F3. `rsync` della `dist/` su `/var/www/aiutami-frontend/`
- [x] F4. Nginx aggiornato: frontend su `/`, API su `/api/`, WS su `/ws/`, HTTPS con redirect
- [x] F5. Verificato: frontend 200, API 401 (JWT ok), admin 200

### Fase G: smoke test

- [ ] G1. Login admin Django da web
- [ ] G2. Creazione sessione da frontend (senza audio)
- [ ] G3. Sessione end-to-end 2 partecipanti (tu + 1 amico) con audio + AI
- [ ] G4. Verificare log backend per errori
- [ ] G5. Verificare transcript STT e interventi AI nei logs
- [ ] G6. Generare report PDF a fine sessione

### Fase H (opzionale): TURN

Solo se durante G3 qualcuno non riesce a connettersi:
- [ ] H1. Installare coturn su stesso droplet
- [ ] H2. Configurare shared-secret auth
- [ ] H3. Aggiungere `turn:aiutami-polimi.me:3478` al config WebRTC frontend
- [ ] H4. Retest

## 5. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Saturazione CPU droplet 2 vCPU con 6 stream | Resize live a 8GB (1 click, 1 min downtime) |
| Partecipanti su NAT simmetrico non si connettono | Installare coturn (Fase H) |
| Crediti DO finiscono a metà tesi | Monitorare consumo, downsizing a Basic 2GB se serve |
| Certificato Let's Encrypt scaduto | Auto-renewal + cron job verifica mensile |
| Leak di `OPENAI_API_KEY` | `.env` mai committato, permessi `600`, rotation se leak |
| Frontend build fuori sync con backend API | Versionare il contract; testare smoke su staging prima di prod |

## 6. Post-deploy (non nello scope immediato)

- Monitoring (Uptime Kuma self-hosted?)
- Backup automatici Postgres (cron + rsync off-site)
- CI/CD GitHub Actions → deploy automatico su push
- Dominio secondario staging (`staging.aiutami-polimi.me`)

---

**Stato corrente:** Fasi A–F **completate**. Frontend + backend live su
`https://aiutami-polimi.me`. Prossimo: Fase G — smoke test end-to-end.
