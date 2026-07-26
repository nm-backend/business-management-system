#!/bin/sh
# =============================================================================
# SkladPro — Manual Certificate Renewal
#
# Run manually: bash scripts/renew-cert.sh
# Or set up a cron job to run monthly:
#   0 3 1 * * /path/to/skladpro/scripts/renew-cert.sh
# =============================================================================

set -e

echo "🔄 Renewing Let's Encrypt certificates..."
docker compose run --rm certbot renew --webroot -w /var/www/certbot --quiet

echo "✓ Renewal complete."

echo "⏳ Reloading nginx to pick up new certificates..."
docker compose exec nginx nginx -s reload

echo "✓ Done!"
