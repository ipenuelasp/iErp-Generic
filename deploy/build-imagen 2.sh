#!/bin/sh
# Construye/actualiza la imagen base de la app (una sola vez por despliegue).
# Todos los contenedores de cliente usan ierp-app:latest.
set -e
cd "$(dirname "$0")/.."
echo "==> Construyendo imagen ierp-app:latest ..."
docker build -t ierp-app:latest -f Dockerfile.prod .
echo "==> Listo."
