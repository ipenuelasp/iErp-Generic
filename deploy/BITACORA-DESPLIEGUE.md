# Bitácora de despliegue — iErp SaaS (ierp.mx)

Registro paso a paso de cómo se creó y levantó todo en producción
(21-jun-2026). Arquitectura: **Opción A** (una sola app + una sola BD,
aislamiento de clientes por subdominio).

```
   *.ierp.mx (DNS en DigitalOcean) ──► Droplet APP (Traefik + app)
                                              │ red privada (VPC)
                                              ▼
                                       Droplet SQL Server (BD ierp_saas)
```

---

## 1. Droplets (DigitalOcean, región NYC1, VPC privada, tag `iErp-SaaS`)
| Nombre | Specs | Rol | IP privada |
|---|---|---|---|
| `iErp-saas-app-prod` | 4 GB / 2 vCPU, Ubuntu 22.04 | Traefik + app | — |
| `iErp-saas-sqlserver-prod` | 4 GB / 2 vCPU, Ubuntu 22.04 | SQL Server | `10.10.0.11` |

Ambos en la **misma VPC** para hablarse por IP privada.

## 2. Firewalls (Cloud Firewalls de DO)
- **`fw-ierp-app`** → aplicado a `iErp-saas-app-prod`:
  - Inbound: `HTTP 80` y `HTTPS 443` (All IPv4/IPv6); `SSH 22` (tu IP o llave).
  - Outbound: todo (default).
- **`fw-ierp-sql`** → aplicado a `iErp-saas-sqlserver-prod`:
  - Inbound: `SSH 22`; `TCP 1433` con **source = el droplet `iErp-saas-app-prod`** (no abierto a internet).
  - Outbound: todo (default).

## 3. Docker (en ambos droplets)
```bash
apt update && apt upgrade -y        # parches de seguridad
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## 4. SQL Server (droplet `iErp-saas-sqlserver-prod`)
SQL Server corre **como contenedor** (no se instala en el sistema):
```bash
docker run -d --name sqlserver --restart always \
  -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=<ClaveSA>" \
  -p 1433:1433 -v sqlvol:/var/opt/mssql \
  mcr.microsoft.com/mssql/server:2022-latest
```
Login + BD de la plataforma (con el contenedor de herramientas):
```bash
docker run --rm --network host mcr.microsoft.com/mssql-tools /opt/mssql-tools/bin/sqlcmd \
  -S localhost,1433 -U sa -P '<ClaveSA>' \
  -Q "CREATE LOGIN ierp_app WITH PASSWORD='<ClaveApp>'; CREATE DATABASE ierp_saas;"
docker run --rm --network host mcr.microsoft.com/mssql-tools /opt/mssql-tools/bin/sqlcmd \
  -S localhost,1433 -U sa -P '<ClaveSA>' -d ierp_saas \
  -Q "CREATE USER ierp_app FOR LOGIN ierp_app; ALTER ROLE db_owner ADD MEMBER ierp_app;"
```
> BD única: **`ierp_saas`** · usuario: **`ierp_app`**. Las claves NO se versionan.

## 5. Aplicación (droplet `iErp-saas-app-prod`)
```bash
git clone https://github.com/ipenuelasp/iErp-Generic.git
cd iErp-Generic && git checkout feat/erp-comercializadora-deploy
docker network create web
docker build -t ierp-app:latest -f Dockerfile.prod .
```
`.env` (raíz del repo — **no se versiona**):
```
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
```
Levantar la app (entrypoint corre migraciones, collectstatic y crea el superusuario):
```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f
```

## 6. Traefik + SSL (droplet `iErp-saas-app-prod`)
```bash
cp deploy/traefik/.env.example deploy/traefik/.env
nano deploy/traefik/.env      # ACME_EMAIL + DO_AUTH_TOKEN (token API de DO, scope domain r/w)
docker compose -f deploy/traefik/docker-compose.yml up -d
```
- Traefik enruta `*.ierp.mx` a la app y emite el **cert wildcard** por **DNS-01** (token de DigitalOcean).
- Imagen `traefik:v3` (la `v3.1` daba error "client version 1.24 too old" con Docker nuevo).

## 7. DNS (DigitalOcean)
- Dominio `ierp.mx` agregado en **Networking → Domains**.
- Nameservers en Squarespace apuntando a `ns1/ns2/ns3.digitalocean.com`.
- Registros **A**: `@` → IP_APP, `*` → IP_APP.

## 8. ⚠️ DNSSEC (problema encontrado y solución)
Al cambiar los nameservers a DigitalOcean (que no firma DNSSEC) con el **DS aún
publicado** en el registro `.mx`, Let's Encrypt fallaba:
`DNSSEC: DNSKEY Missing ... while building chain of trust`.
**Solución:** desactivar DNSSEC en Squarespace (quitar el registro DS). Verificar:
```bash
dig DS ierp.mx @1.1.1.1 +short   # debe quedar VACÍO en todos los resolvers
dig DS ierp.mx @8.8.8.8 +short
```
La baja del DS **tarda en propagar** (TTL del `.mx`, de minutos a horas). Mientras
algún resolver lo vea, el cert falla. No reintentar en exceso (rate limit LE ~5/hora);
Traefik reintenta solo y emite el cert cuando el DS termina de limpiarse.

## 9. Operación diaria
- **Portal proveedor (superadmin):** `https://admin.ierp.mx`
- **Portal de cliente:** `https://<slug>.ierp.mx` (el `slug` = `ClienteSaaS.slug_instancia`)
- **Alta de cliente:** se hace **desde la app** (crear `ClienteSaaS` con su slug + invitar dueño). No requiere tocar el servidor.

## 10. Actualizar el software (deploy de cambios)
```bash
cd iErp-Generic && git pull
docker compose -f docker-compose.prod.yml up -d --build
```
Migraciones corren solas sobre `ierp_saas`. Un push = todos los clientes actualizados.

## 11. Comandos útiles
```bash
docker ps                                   # contenedores
docker logs ierp_app --tail 50              # logs de la app
docker logs traefik 2>&1 | grep -i acme     # estado del certificado
grep -o '"main":"[^"]*"' deploy/traefik/letsencrypt/acme.json   # cert emitido
```

## 12. Respaldos
- BD: `BACKUP DATABASE ierp_saas ...` en el droplet SQL Server (o respaldar el volumen `sqlvol`).
- Medios/estáticos de la app: `/var/www/ierp/` en el droplet APP.

---
### Pendientes
- Esperar propagación del DS para que se emita el cert wildcard (en curso).
- Quitar `--log.level=DEBUG` de `deploy/traefik/docker-compose.yml` cuando ya esté estable.
- Fase 2: panel del proveedor para alta de clientes desde la app.
- Auto-deploy con GitHub Actions (push → SSH → pull/build/restart).
