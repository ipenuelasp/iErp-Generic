#!/usr/bin/env bash
# Da de alta un cliente nuevo: prepara su carpeta, .env y lo levanta detrás de Traefik.
#
#   ./nuevo-cliente.sh <slug> [subdominio]
#   ./nuevo-cliente.sh ipenuelas                 -> ipenuelas.ierp.mx
#   ./nuevo-cliente.sh acuagro acuagro.ierp.mx
#
# Antes de levantar, debes:
#   1) Crear la BD en el droplet de SQL Server (ver README-DEPLOY.md, sección 3).
#   2) Construir la imagen una vez:  ./build-imagen.sh
#   3) Editar el .env generado y poner SECRET_KEY, DB_HOST, DB_PASS y password admin.
set -euo pipefail

DOMINIO="${DOMINIO:-ierp.mx}"
SLUG="${1:?Uso: ./nuevo-cliente.sh <slug> [subdominio]}"
SUBDOMINIO="${2:-${SLUG}.${DOMINIO}}"

DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${DIR}/clientes/${SLUG}"

mkdir -p "${DEST}/media" "${DEST}/staticfiles" "${DEST}/logs"

# Render del compose con SLUG y SUBDOMINIO
SLUG="${SLUG}" SUBDOMINIO="${SUBDOMINIO}" \
  envsubst '${SLUG} ${SUBDOMINIO}' < "${DIR}/cliente.compose.yml" > "${DEST}/docker-compose.yml"

# .env (solo si no existe, para no pisar secretos)
if [ ! -f "${DEST}/.env" ]; then
  sed -e "s/__SUBDOMINIO__/${SUBDOMINIO}/g" -e "s/__SLUG__/${SLUG}/g" \
    "${DIR}/.env.cliente.example" > "${DEST}/.env"
  echo ">> Generé ${DEST}/.env  — EDÍTALO (SECRET_KEY, DB_HOST, DB_PASS, password admin) antes de continuar."
  echo ">> Cuando esté listo, vuelve a correr:  ./nuevo-cliente.sh ${SLUG} ${SUBDOMINIO}"
  exit 0
fi

echo "==> Levantando cliente ${SLUG} (${SUBDOMINIO}) ..."
cd "${DEST}"
docker compose -p "ierp-${SLUG}" up -d
echo "==> ${SUBDOMINIO} arriba. El entrypoint corre migraciones, estáticos y crea el superusuario."
echo "==> Verifica:  docker compose -p ierp-${SLUG} logs -f"
