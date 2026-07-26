#!/bin/sh
# =============================================================================
# SkladPro — Certbot Initial Certificate Request
#
# Steps:
#   1. Make sure DNS A-record points to this server's IP
#   2. Run: docker compose build --pull && docker compose up -d db redis
#   3. Run: bash scripts/certbot-init.sh
#
# The script:
#   a. Generates a self-signed placeholder cert so nginx can start
#   b. Starts nginx (port 80 with ACME challenge)
#   c. Requests real certificate from Let's Encrypt
#   d. Creates symlink for nginx
#   e. Restarts nginx with full HTTPS
# =============================================================================

set -e

# Load .env variables
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
else
    echo "❌ .env file not found. Create it from .env.prod.example first."
    exit 1
fi

DOMAIN="${DOMAIN_NAME:-}"
EMAIL="${DOMAIN_EMAIL:-admin@${DOMAIN}}"

if [ -z "$DOMAIN" ]; then
    echo "❌ DOMAIN_NAME is not set in .env"
    echo "   Add: DOMAIN_NAME=skladpro.example.com"
    exit 1
fi

echo "🔐 Setting up SSL/TLS for domain: $DOMAIN"
echo "   Email: $EMAIL"

# ==================== Step 1: Generate self-signed placeholder ====================
# nginx.conf references /etc/letsencrypt/live/skladpro/*.pem.
# These files must exist before nginx starts, or nginx will fail.
echo ""
echo "⏳ Creating self-signed placeholder certificate..."
docker compose run --rm --no-deps --entrypoint sh certbot -c "
  mkdir -p /etc/letsencrypt/live/skladpro
  openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
    -keyout /etc/letsencrypt/live/skladpro/privkey.pem \
    -out /etc/letsencrypt/live/skladpro/fullchain.pem \
    -subj '/CN=localhost' 2>/dev/null
  echo '✓ Self-signed placeholder cert created'
" 2>/dev/null
echo ""

# ==================== Step 2: Generate DH params ====================
echo "⏳ Generating DH parameters (if needed)..."
docker compose run --rm dhparam 2>/dev/null || true
echo ""

# ==================== Step 3: Start nginx (port 80 for ACME challenge) ====================
echo "⏳ Starting nginx on port 80 (ACME challenge)..."
docker compose up -d nginx
echo "   Waiting 5s for nginx..."
sleep 5

# ==================== Step 4: Request Let's Encrypt certificate ====================
echo "⏳ Requesting Let's Encrypt certificate..."
docker compose run --rm certbot certonly --webroot \
    --webroot-path /var/www/certbot \
    --email "$EMAIL" \
    --domain "$DOMAIN" \
    --agree-tos \
    --non-interactive \
    --no-eff-email

echo ""
echo "✓ Certificate obtained for: $DOMAIN"

# ==================== Step 5: Create symlink for nginx ====================
# nginx expects certs at /etc/letsencrypt/live/skladpro/ (fixed path)
# certbot stores them at /etc/letsencrypt/live/$DOMAIN/ (domain-based path)
echo "🔗 Creating symlink: /etc/letsencrypt/live/skladpro → $DOMAIN"
docker compose run --rm --no-deps --entrypoint sh certbot -c "
  ln -sfT /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/live/skladpro
  echo '✓ Symlink created'
"
echo ""

# ==================== Step 6: Restart nginx with HTTPS ====================
echo "⏳ Restarting nginx with HTTPS..."
docker compose up -d --force-recreate nginx

echo ""
echo "✓ SSL/TLS setup complete!"
echo "📁 Certificate: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "🔗 Symlink:     /etc/letsencrypt/live/skladpro → $DOMAIN"
echo ""
echo "Test: curl https://$DOMAIN/health/"
