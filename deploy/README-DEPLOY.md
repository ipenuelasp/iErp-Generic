# Despliegue iErp — un droplet de app (Traefik + contenedor por cliente) + droplet de SQL Server

Arquitectura:

```
                 *.ierp.mx (DNS -> IP droplet APP)
   ┌─────────────────── Droplet APP (Docker) ───────────────────┐
   │  Traefik (80/443, SSL Let's Encrypt)                        │
   │   ├─ ierp_ipenuelas   -> ipenuelas.ierp.mx                  │
   │   ├─ ierp_insermed    -> insermed.ierp.mx                   │
   │   └─ ierp_acuagro     -> acuagro.ierp.mx                    │
   └───────────────────────────┬─────────────────────────────────┘
                               │ red privada (1433)
                    ┌──────────┴───────────┐
                    │ Droplet SQL SERVER   │  BDs: ierp_ipenuelas,
                    │ (mssql en Docker)    │       ierp_insermed, ...
                    └──────────────────────┘
```

Cada cliente = su contenedor + su BD + su subdominio. La BD **no** se crea desde la
app: se provisiona aquí con `nuevo-cliente.sh` + un `CREATE DATABASE`.

---

## Tamaños sugeridos
- **Droplet APP:** 4 GB / 2 vCPU.
- **Droplet SQL Server:** 4 GB / 2 vCPU + Volume SSD para datos.
- Ambos en la **misma región** y usa **red privada (VPC)** para que se hablen por IP interna.

---

## 1. Droplet SQL Server
```bash
# En el droplet SQL Server (Ubuntu + Docker):
docker run -d --name sqlserver --restart always \
  -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=UnaClaveFuerte!2026" \
  -p 1433:1433 -v sqlvol:/var/opt/mssql \
  mcr.microsoft.com/mssql/server:2022-latest
```
- Firewall (DO): permite el puerto **1433 solo desde la IP privada del droplet APP**.
- Crea un login de app (una vez):
```sql
CREATE LOGIN ierp_app WITH PASSWORD = 'OtraClaveFuerte!2026';
```

## 2. Droplet APP
```bash
# Docker + compose ya instalados. Clona el repo:
git clone https://github.com/ipenuelasp/iErp-Generic.git
cd iErp-Generic
docker network create web                 # red compartida con Traefik

# Traefik
cd deploy/traefik
ACME_EMAIL=tu-correo@dominio.com docker compose up -d
cd ../..

# Imagen base de la app (una vez; repite tras cada git pull):
./deploy/build-imagen.sh
```

## 3. Crear la BD de un cliente (en el droplet SQL Server)
```sql
CREATE DATABASE ierp_ipenuelas;
USE ierp_ipenuelas;
CREATE USER ierp_app FOR LOGIN ierp_app;
ALTER ROLE db_owner ADD MEMBER ierp_app;
```

## 4. Levantar el cliente (en el droplet APP)
```bash
cd deploy
./nuevo-cliente.sh ipenuelas          # 1ra vez: genera clientes/ipenuelas/.env
nano clientes/ipenuelas/.env          # pon SECRET_KEY, DB_HOST (IP privada SQL), DB_PASS, password admin
./nuevo-cliente.sh ipenuelas          # 2da vez: lo levanta
```
El `entrypoint.sh` corre migraciones (crea tablas), `collectstatic` y crea el superusuario.
Repite los pasos 3–4 para `insermed`, `acuagro`, etc.

## 5. DNS
En tu proveedor de DNS de **ierp.mx**, apunta a la **IP pública del droplet APP**:
- `A  ipenuelas.ierp.mx  -> IP_APP`
- `A  insermed.ierp.mx   -> IP_APP`
- `A  acuagro.ierp.mx    -> IP_APP`
(o un registro comodín `A  *.ierp.mx -> IP_APP`)

Al primer acceso por HTTPS, Traefik emite el certificado SSL automáticamente.

## 6. Entrar y configurar
Abre `https://ipenuelas.ierp.mx`, entra con el superusuario del `.env`, y crea
ahí la(s) Empresa(s), sucursales, módulos y usuarios de ese cliente.

## 7. Actualizar (deploy de cambios)
```bash
cd iErp-Generic
git pull
./deploy/build-imagen.sh
# recrear cada cliente con la imagen nueva:
for c in deploy/clientes/*/; do (cd "$c" && docker compose -p "ierp-$(basename "$c")" up -d); done
```
> El auto-deploy por GitHub Actions (push -> SSH -> pull -> build -> up) se configura aparte.

## Notas
- Los `.env` y datos de cada cliente viven en `deploy/clientes/<slug>/` y **no** se suben a git.
- Backups: respalda las BD en el droplet SQL Server (`BACKUP DATABASE ...` o dump del volumen).
