# Despliegue iErp SaaS — Opción A (BD compartida, aislamiento por subdominio)

Arquitectura:

```
                 *.ierp.mx  (DNS -> IP pública del droplet APP)
   ┌──────────────── Droplet APP (iErp-saas-app-prod) ────────────────┐
   │  Traefik (80/443, cert wildcard *.ierp.mx por DNS-01)            │
   │     └─ ierp_app  (UNA app, UNA BD; el tenant se resuelve por      │
   │                   subdominio: <slug>.ierp.mx -> ClienteSaaS)      │
   └───────────────────────────┬──────────────────────────────────────┘
                               │ red privada (VPC, 1433)
                    ┌──────────┴────────────────┐
                    │ Droplet SQL SERVER         │  BD única: ierp_saas
                    │ (iErp-saas-sqlserver-prod) │
                    └────────────────────────────┘
```

- **Una sola app + una sola BD** (`ierp_saas`). Los clientes se dan de alta
  **desde la app** (no por script); el subdominio sólo enfoca al tenant.
- Cada cliente (`ClienteSaaS`) tiene su `slug_instancia` = subdominio.

---

## 1. Droplet SQL Server (iErp-saas-sqlserver-prod)
```bash
docker run -d --name sqlserver --restart always \
  -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=<ClaveSA>" \
  -p 1433:1433 -v sqlvol:/var/opt/mssql \
  mcr.microsoft.com/mssql/server:2022-latest
```
Crear login y BD (con el contenedor de herramientas):
```bash
docker run --rm --network host mcr.microsoft.com/mssql-tools /opt/mssql-tools/bin/sqlcmd \
  -S localhost,1433 -U sa -P '<ClaveSA>' \
  -Q "CREATE LOGIN ierp_app WITH PASSWORD='<ClaveApp>'; CREATE DATABASE ierp_saas;"
docker run --rm --network host mcr.microsoft.com/mssql-tools /opt/mssql-tools/bin/sqlcmd \
  -S localhost,1433 -U sa -P '<ClaveSA>' -d ierp_saas \
  -Q "CREATE USER ierp_app FOR LOGIN ierp_app; ALTER ROLE db_owner ADD MEMBER ierp_app;"
```
Firewall: 1433 sólo desde el droplet APP (usar el Droplet como source).

## 2. DNS de ierp.mx en DigitalOcean
- Networking → Domains → agrega `ierp.mx`. En tu registrador, apunta los
  nameservers a `ns1/ns2/ns3.digitalocean.com`.
- Registros A (a la **IP pública del droplet APP**):
  - `@`  → IP_APP   (dominio raíz)
  - `*`  → IP_APP   (todos los subdominios de clientes)
- Crea un **token de API** (Networking/API, read+write) para el reto DNS.

## 3. Droplet APP (iErp-saas-app-prod)
```bash
git clone https://github.com/ipenuelasp/iErp-Generic.git
cd iErp-Generic
git checkout feat/erp-comercializadora-deploy
docker network create web
docker build -t ierp-app:latest -f Dockerfile.prod .

# .env de la app (raíz del repo)
cat > .env <<'EOF'
DEBUG=False
SECRET_KEY=<openssl rand -base64 48>
BASE_DOMAIN=ierp.mx
ALLOWED_HOSTS=.ierp.mx
DB_HOST=10.10.0.11
DB_PORT=1433
DB_NAME=ierp_saas
DB_USER=ierp_app
DB_PASS=<ClaveApp>
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@ierp.mx
DJANGO_SUPERUSER_PASSWORD=<ClaveAdmin>
EOF

# Traefik (cert wildcard por DNS-01)
cp deploy/traefik/.env.example deploy/traefik/.env
nano deploy/traefik/.env        # ACME_EMAIL + DO_AUTH_TOKEN
docker compose -f deploy/traefik/docker-compose.yml up -d

# La app
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f   # ver migraciones/arranque
```

## 4. Probar
- `https://admin.ierp.mx` → portal del proveedor (superadmin) → login.
- Crea un `ClienteSaaS` con `slug_instancia=ipenuelas` → entra a `https://ipenuelas.ierp.mx`.

## 5. Actualizar (deploy de cambios)
```bash
cd iErp-Generic && git pull
docker compose -f docker-compose.prod.yml up -d --build
```
Las migraciones corren solas (entrypoint) sobre `ierp_saas`. Un push = todos los clientes actualizados (misma app/BD).

## Notas
- `.env` (raíz) y `deploy/traefik/.env` **no** se versionan.
- Estáticos/medios persisten en `/var/www/ierp/` del droplet APP.
- Backup: respalda la BD `ierp_saas` en el droplet SQL Server.
