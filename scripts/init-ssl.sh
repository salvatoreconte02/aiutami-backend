#!/bin/bash
# init-ssl.sh — Prima configurazione HTTPS con Let's Encrypt
# Eseguire UNA SOLA VOLTA sul server, dopo aver puntato il dominio alla VPS.
#
# Uso: ./scripts/init-ssl.sh tuodominio.com email@example.com

set -e

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Uso: $0 <dominio> <email>"
    echo "Esempio: $0 api.aiutami.it tuo@email.com"
    exit 1
fi

COMPOSE="docker compose -f docker-compose.prod.yml"

echo "==> 1/5 Sostituisco il dominio nella config Nginx..."
sed -i "s/DOMINIO_DA_CONFIGURARE/$DOMAIN/g" nginx/nginx.conf

echo "==> 2/5 Creo certificato self-signed temporaneo..."
# Nginx non parte senza certificati, quindi ne creiamo uno finto
mkdir -p ./certbot-temp
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout ./certbot-temp/privkey.pem \
    -out ./certbot-temp/fullchain.pem \
    -subj "/CN=$DOMAIN" 2>/dev/null

# Copiamo il cert temporaneo nel volume
$COMPOSE up -d nginx
docker cp ./certbot-temp/fullchain.pem aiutami-nginx:/etc/letsencrypt/live/$DOMAIN/fullchain.pem 2>/dev/null || true
docker cp ./certbot-temp/privkey.pem aiutami-nginx:/etc/letsencrypt/live/$DOMAIN/privkey.pem 2>/dev/null || true

# Metodo alternativo: creiamo la struttura nel volume
$COMPOSE down
docker volume rm aiutami-backend_certbot-etc 2>/dev/null || true
$COMPOSE run --rm --entrypoint "" certbot sh -c "
    mkdir -p /etc/letsencrypt/live/$DOMAIN &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
        -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
        -subj '/CN=$DOMAIN'
"
rm -rf ./certbot-temp

echo "==> 3/5 Avvio Nginx con certificato temporaneo..."
$COMPOSE up -d nginx

echo "==> 4/5 Richiedo certificato vero a Let's Encrypt..."
$COMPOSE run --rm certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

echo "==> 5/5 Riavvio Nginx con certificato vero..."
$COMPOSE exec nginx nginx -s reload

echo ""
echo "Fatto! HTTPS attivo su https://$DOMAIN"
echo ""
echo "Per il rinnovo automatico, aggiungi questo cron job:"
echo "  0 3 * * * cd $(pwd) && $COMPOSE run --rm certbot renew && $COMPOSE exec nginx nginx -s reload"
