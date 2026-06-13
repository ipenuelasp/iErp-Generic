# Manual del Agente TI
**Sistema de Helpdesk TI — Grupo Gonza**
**Acceso:** https://ti.grupogonza.phanalytics.com.mx

---

## Acceso al sistema

### Desde computadora
1. Abre `https://ti.grupogonza.phanalytics.com.mx`
2. Ingresa tu usuario y contraseña
3. El sistema te llevará directamente al **Panel de Tickets**

### Desde celular (PWA)
1. Abre `https://ti.grupogonza.phanalytics.com.mx` en Safari (iPhone) o Chrome (Android)
2. Toca **"Agregar a pantalla de inicio"** o **"Instalar app"**
3. Se instalará como aplicación nativa
4. Al abrir la app verás el **Dashboard Móvil** con tus KPIs personales

---

## Panel principal (escritorio)

Al ingresar verás el **Panel de Tickets** con:

- Lista de todos los tickets activos con filtros por estatus, prioridad y agente asignado
- Buscador por folio, asunto o solicitante
- Acceso rápido a catálogos y reportes

### Navegación principal

| Sección | Qué contiene |
|---|---|
| **Panel** | Lista de tickets activos con filtros |
| **Reportes** | Estadísticas de productividad |
| **Catálogos** | Empresas, departamentos, categorías, prioridades, agentes |

---

## Flujo de estatus de un ticket

### Diagrama de transiciones

```
                    ┌─────────┐
   Ticket nuevo ──► │ ABIERTO │
                    └────┬────┘
                         │ Se asigna agente
                         ▼
                    ┌──────────┐
                    │ ASIGNADO │
                    └────┬─────┘
                         │ Agente toma el caso
                         ▼
                   ┌────────────┐ ◄──────────────────────────────────┐
                   │ EN ATENCIÓN │                                    │
                   └──────┬──────┘                                   │
           ┌──────────────┼──────────────┬──────────────┐            │
           ▼              ▼              ▼              ▼            │
  ┌────────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
  │ EN ESPERA DE   │  │PENDIENTE │  │PENDIENTE │  │EN ESPERA │     │
  │ AUTORIZACIÓN   │  │DE COMPRA │  │PROVEEDOR │  │INFO SOL. │     │
  └───────┬────────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
          │                │              │              │            │
     ┌────┴────┐      ┌────┴──────┐       └──────────────┴───────────┘
     ▼         ▼      ▼          ▼
┌──────────┐ ┌───────────┐  ┌──────────┐
│ RECHAZADO│ │ PENDIENTE │  │ RESUELTO │──► CERRADO
└──────────┘ │ ENTREGA   │  └──────────┘
             └─────┬─────┘       ▲
                   └─────────────┘
```

### Descripción de cada estatus

| Estatus | Significado | Quién actúa | Siguiente paso |
|---|---|---|---|
| **Abierto** | Ticket recibido, sin asignar | Administrador TI | Asignar a un agente |
| **Asignado** | Agente designado, pendiente de inicio | Agente | Cambiar a En Atención al empezar a trabajar |
| **En Atención** | Agente trabajando activamente | Agente | Resolver, o pasar a un estado de espera según lo que se necesite |
| **En Espera de Autorización** | Requiere aprobación de dirección antes de ejecutar | Dirección / Admin | Dirección autoriza → vuelve a En Atención; o Rechazar |
| **En Espera de Información** | Falta información del solicitante para continuar | Solicitante | Cuando el solicitante responde → vuelve a En Atención |
| **En Espera de Proveedor** | Se escaló a soporte externo | Proveedor externo | Cuando el proveedor responde → vuelve a En Atención |
| **Pendiente de Compra** | Se requiere adquirir hardware, licencia u otro insumo | Área de compras | Cuando se realiza la compra → Pendiente de Entrega; o volver a En Atención si se cancela |
| **Pendiente de Entrega** | Insumo comprado, en tránsito o pendiente de recibir | Almacén / Proveedor | Al recibir → vuelve a En Atención o cierra en Resuelto |
| **Resuelto** | El agente marcó el ticket como atendido | Solicitante confirma | Si el solicitante está de acuerdo → Cerrado; si reabre → vuelve a En Atención |
| **Cerrado** | Ticket completamente concluido | — | Estado final. No se puede modificar |
| **Cancelado** | Solicitud cancelada (por el agente o admin) | — | Estado final |
| **Rechazado** | Solicitud de autorización denegada por dirección | — | Estado final |

---

## Atender un ticket paso a paso

### 1. Tomar un ticket asignado

1. En el panel, localiza tickets en estatus **Asignado** con tu nombre
2. Abre el ticket para ver el detalle completo
3. Lee la descripción y adjuntos del solicitante
4. Cambia el estatus a **En Atención** cuando comiences a trabajar en él

### 2. Comunicarte con el solicitante

Dentro del ticket encontrarás el panel de mensajes:

- **Mensaje visible al solicitante:** El solicitante lo recibe por correo y puede verlo en su enlace de seguimiento
- **Nota interna:** Solo la ve el equipo de TI — útil para coordinar entre agentes o registrar pasos técnicos

> Usa notas internas para dejar documentado lo que hiciste: comandos ejecutados, configuraciones cambiadas, diagnóstico, etc.

### 3. Pedir información adicional

Si necesitas más datos del solicitante:
1. Escribe un mensaje explicando qué información necesitas
2. Cambia el estatus a **En Espera de Información**
3. El solicitante recibirá notificación por correo
4. Cuando responda, vuelve el estatus a **En Atención**

### 4. Solicitar autorización

Para solicitudes que requieren aprobación (o cuando detectas que se necesita):
1. Escribe una nota explicando qué se va a ejecutar y por qué
2. Cambia el estatus a **En Espera de Autorización**
3. El administrador TI enviará la solicitud a dirección
4. Si se autoriza → el ticket vuelve a **En Atención**
5. Si se rechaza → el ticket queda en **Rechazado** y se notifica al solicitante

### 5. Cuando involucra compra de equipo o licencia

1. Documenta en una nota interna qué se necesita comprar (descripción, cantidad, precio estimado si lo sabes)
2. Cambia a **Pendiente de Compra**
3. Al confirmar la compra, cambia a **Pendiente de Entrega**
4. Al recibir el insumo y completar la instalación/entrega, resuelve el ticket

### 6. Resolver el ticket

1. Documenta en el mensaje qué se hizo para resolver
2. Cambia el estatus a **Resuelto**
3. El solicitante recibe correo notificándole
4. Si el solicitante confirma → el ticket pasa a **Cerrado**
5. Si el solicitante reporta que sigue el problema → vuelve a **En Atención**

> El ticket se cierra automáticamente si el solicitante no objeta en el plazo definido.

---

## Tareas internas (🔒)

Los tickets internos son tareas que el Administrador TI crea directamente y asigna a un agente. **No son generadas por un solicitante externo.**

Se identifican con el ícono 🔒 en la lista de tickets.

**Características:**
- No envían notificaciones por correo al "solicitante" (porque es una tarea interna)
- Arrancan directamente en estatus **Asignado**
- Siguen el mismo flujo de estatus que un ticket normal
- Se pueden ver en tu lista de tickets como cualquier otra

---

## Dashboard móvil (PWA)

Cuando accedes desde el celular verás tu panel personal con:

### KPIs visibles como agente

| Tarjeta | Qué muestra |
|---|---|
| **Mis tickets activos** | Total de tickets abiertos asignados a ti |
| **En atención** | Tickets que tienes actualmente en proceso |
| **Resueltos hoy** | Tickets que resolviste en el día |
| **Pendiente de info** | Tickets en espera de respuesta del solicitante |

### Navegación móvil

| Ícono | Sección |
|---|---|
| 🏠 Inicio | Dashboard con tus KPIs |
| 📋 Tickets | Lista de tus tickets asignados |
| ➕ Nuevo | Formulario para crear ticket nuevo |
| 📊 Reportes | Tu reporte de productividad personal |
| 👤 Perfil | Tu información y cerrar sesión |

---

## Tu reporte de productividad

En la sección **Reportes** encontrarás tu scorecard personal:

- **Score de productividad (0–100):** Calculado en base a tasa de resolución, tiempo promedio, tickets activos y pendientes de información
- **Tickets resueltos** vs **Total atendidos**
- **Tiempo promedio de resolución**
- **Actividad de los últimos 7 días** (gráfica de barras)
- **Tickets activos actuales** con prioridad
- **Últimos tickets resueltos**

---

## Buenas prácticas

1. **Actualiza el estatus siempre** — El solicitante ve el estatus en tiempo real. Un ticket "Asignado" durante días genera ansiedad innecesaria.

2. **Deja notas internas detalladas** — Documenta cada acción técnica. Si otro agente debe tomar el ticket, podrá continuar sin preguntar.

3. **Responde rápido a los "En Espera de Información"** — Son tickets bloqueados. En cuanto el solicitante responda, retómalos inmediatamente.

4. **Usa la prioridad correctamente** — Si un ticket está mal priorizado, corrígelo y explica el motivo en una nota.

5. **No dejes tickets en Resuelto mucho tiempo** — Una vez que el solicitante confirma o pasa el plazo, ciérralos para que no inflen tus métricas de activos.

---

*Soporte al sistema: ipenuelas@phanalytics.com.mx*
