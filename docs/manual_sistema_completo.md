# Manual del Sistema — Helpdesk TI Grupo Gonza
**Versión 1.0 — Junio 2026**
**Portal:** https://ti.grupogonza.phanalytics.com.mx

---

## Índice

1. [Descripción general del sistema](#1-descripción-general-del-sistema)
2. [Tipos de usuario](#2-tipos-de-usuario)
3. [Módulo Solicitante — Crear y dar seguimiento a tickets](#3-módulo-solicitante)
4. [Módulo Agente TI — Atención y resolución](#4-módulo-agente-ti)
5. [Módulo Administrador TI — Gestión y supervisión](#5-módulo-administrador-ti)
6. [Flujo completo de un ticket](#6-flujo-completo-de-un-ticket)
7. [Catálogos del sistema](#7-catálogos-del-sistema)
8. [Aplicación móvil (PWA)](#8-aplicación-móvil-pwa)
9. [Notificaciones por correo](#9-notificaciones-por-correo)
10. [Glosario](#10-glosario)

---

## 1. Descripción general del sistema

El **Helpdesk TI de Grupo Gonza** es una plataforma centralizada para la gestión de solicitudes de soporte tecnológico dentro de todas las empresas del grupo. Su objetivo es:

- Registrar y dar trazabilidad a cada solicitud de TI
- Distribuir la carga de trabajo entre los agentes del equipo
- Mantener informado al solicitante en cada etapa del proceso
- Generar métricas de productividad y cumplimiento
- Preservar el historial completo de cada ticket y acción tomada

### Tecnología

El sistema opera como aplicación web disponible desde cualquier navegador, y como **aplicación instalable en celular (PWA)** para el equipo de TI. No requiere instalación de software adicional en computadoras de oficina.

---

## 2. Tipos de usuario

| Rol | Acceso | Descripción |
|---|---|---|
| **Solicitante** | Sin login — acceso por enlace único | Cualquier colaborador del Grupo Gonza. Registra tickets y da seguimiento desde su correo. |
| **Agente TI** | Login con usuario y contraseña | Miembro del equipo de TI. Atiende y resuelve tickets asignados. |
| **Administrador TI** | Login con permisos de superusuario | Gerente o responsable de TI. Tiene acceso total: asignación, catálogos, reportes globales y tareas internas. |

---

## 3. Módulo Solicitante

### 3.1 Acceso

El solicitante no necesita cuenta. Accede directamente al formulario público:

```
https://ti.grupogonza.phanalytics.com.mx/sistemas/tickets/nueva-solicitud/
```

### 3.2 Registrar un ticket

El formulario solicita:

| Campo | Descripción |
|---|---|
| **Empresa** | Empresa del Grupo Gonza a la que pertenece |
| **Departamento** | Área de trabajo del solicitante |
| **Nombre completo** | Nombre para identificarlo en el sistema |
| **Correo electrónico** | Dirección donde recibirá el folio y las notificaciones |
| **Categoría** | Tipo de solicitud (solo se muestran categorías públicas) |
| **Prioridad** | Nivel de urgencia estimado |
| **Asunto** | Título breve descriptivo del problema |
| **Descripción** | Detalle completo: qué ocurre, desde cuándo, impacto |
| **Adjuntos** | Capturas de pantalla, fotos, archivos de apoyo |

#### Categorías públicas disponibles

| Categoría | Cuándo usarla |
|---|---|
| Conectividad | Red, internet, VPN, acceso a sistemas |
| Correo electrónico | Outlook, envío/recepción |
| Impresoras y periféricos | Impresoras, escáneres, dispositivos |
| Hardware / Equipo | Computadora, pantalla, hardware físico |
| Software / Aplicaciones | Programas, licencias, instalaciones |
| Accesos y permisos | Solicitud de acceso a sistemas o recursos |
| Desarrollo / Nueva funcionalidad | Mejoras o nuevas funciones en sistemas internos |

> Las categorías marcadas como **internas** (como ajustes de desarrollo existente) no aparecen en este formulario — son exclusivas del equipo de TI.

#### Niveles de prioridad

| Prioridad | Cuándo aplica |
|---|---|
| 🔴 Crítica | Detiene completamente la operación |
| 🟠 Alta | Afecta significativamente pero hay alternativa temporal |
| 🟡 Media (predeterminada) | Inconveniente moderado, puede esperar |
| 🟢 Baja | Consulta o mejora sin urgencia |

### 3.3 Seguimiento del ticket

Al enviar el formulario, el solicitante recibe un **correo de confirmación** con:

- **Número de folio** (ej. `TK-0042`)
- **Enlace único de seguimiento** — exclusivo para ese ticket

Desde ese enlace puede:
- Ver el estatus actual
- Leer mensajes del equipo de TI
- Agregar comentarios o información adicional
- Ver los adjuntos subidos

### 3.4 Notificaciones automáticas

El solicitante recibe correo en los siguientes eventos:

| Evento | Correo enviado |
|---|---|
| Ticket creado | Confirmación con folio y enlace de seguimiento |
| Ticket asignado | Notificación de que un agente tomó el caso |
| Mensaje del agente | El contenido del mensaje (mensajes públicos únicamente) |
| Ticket resuelto | Notificación para confirmar resolución |
| Ticket cerrado | Confirmación de cierre |

---

## 4. Módulo Agente TI

### 4.1 Acceso

Los agentes ingresan con usuario y contraseña en:
```
https://ti.grupogonza.phanalytics.com.mx
```

### 4.2 Panel de tickets

Muestra la lista de tickets con filtros por:
- Estatus
- Prioridad
- Agente asignado
- Fecha

### 4.3 Atención de tickets

Al abrir un ticket, el agente puede:

- **Ver el historial completo** de mensajes y cambios de estatus
- **Enviar mensajes** al solicitante (visibles en el seguimiento)
- **Escribir notas internas** (solo visibles para el equipo de TI)
- **Cambiar el estatus** del ticket según avance
- **Subir adjuntos** de resolución (capturas, evidencias)
- **Reasignar** el ticket a otro agente (administrador)

### 4.4 Transiciones de estatus disponibles para el agente

| Estatus actual | Puede cambiar a |
|---|---|
| Asignado | En Atención, En Espera de Autorización, Cancelado |
| En Atención | En Espera de Autorización, En Espera de Información, En Espera de Proveedor, Pendiente de Compra, Resuelto, Cancelado |
| En Espera de Información | En Atención |
| En Espera de Proveedor | En Atención |
| Pendiente de Compra | Pendiente de Entrega, En Atención, Cancelado |
| Pendiente de Entrega | En Atención, Resuelto |
| Resuelto | Cerrado, En Atención |

### 4.5 Tipos de mensaje

| Tipo | Visible para | Uso recomendado |
|---|---|---|
| **Mensaje al solicitante** | Agente + Solicitante | Pedirle información, informarle avances, notificar resolución |
| **Nota interna** | Solo equipo TI | Documentar pasos técnicos, diagnósticos, coordinación interna |

### 4.6 Dashboard móvil del agente

El agente accede desde su celular con la PWA instalada y ve:

- Mis tickets activos
- En atención
- Resueltos hoy
- Pendiente de información

Y tiene acceso rápido a su lista de tickets y su reporte de productividad.

---

## 5. Módulo Administrador TI

### 5.1 Acceso

El administrador TI (superusuario) tiene acceso a todas las funcionalidades. Inicia sesión igual que el agente.

### 5.2 Funcionalidades exclusivas

#### Asignación de tickets

Desde el detalle de cualquier ticket puede:
- Asignar o reasignar el ticket a cualquier agente activo
- Ver la carga de trabajo de cada agente (tickets asignados actualmente)

#### Solicitar autorización a dirección

Para tickets que requieren aprobación:
1. Dentro del ticket (desde móvil o escritorio) aparece la sección **"Solicitar autorización"**
2. Escribe el resumen de lo que se va a ejecutar
3. El sistema registra la solicitud y cambia el estatus a **En Espera de Autorización**

#### Tareas internas 🔒

El administrador puede crear **tickets internos** para asignar trabajo directo al equipo de TI sin que provenga de un solicitante externo:

- Acceso desde el panel: **Panel → Nueva tarea interna**
- Acceso desde la app móvil: botón **🔒 Tarea** en la navegación inferior

Las tareas internas:
- Solo usan categorías marcadas como `Internas`
- No envían correo de seguimiento a ningún solicitante
- Arrancan directamente en estatus **Asignado**
- Se identifican con el ícono 🔒 en todas las listas

#### Dashboard global (móvil)

El administrador ve en su app el tablero completo del equipo:

| KPI | Descripción |
|---|---|
| Tickets abiertos | Total sin asignar |
| En atención | Total en proceso activo |
| Resueltos hoy | Total resueltos en el día |
| Pendiente de info | En espera de respuesta del solicitante |
| Sin asignar | Abiertos que aún no tienen agente |
| Esta semana | Tickets creados en los últimos 7 días |

#### Reportes globales

Accede desde **Reportes** en el menú:
- Resumen por agente: tickets atendidos, resueltos, tiempo promedio
- Distribución por categoría y prioridad
- Tendencia semanal

#### Catálogos

El administrador gestiona todos los catálogos del sistema (ver sección 7).

---

## 6. Flujo completo de un ticket

### Flujo estándar (sin autorización)

```
Solicitante llena formulario
        │
        ▼
   [ABIERTO] ──► Correo de confirmación al solicitante
        │
        │ Administrador asigna agente
        ▼
   [ASIGNADO] ──► Correo al solicitante: "Tu ticket fue asignado"
        │
        │ Agente toma el caso
        ▼
   [EN ATENCIÓN]
        │
        ├─► Necesita info ──► [EN ESPERA DE INFORMACIÓN] ──► Solicitante responde ──► [EN ATENCIÓN]
        │
        ├─► Necesita proveedor ──► [EN ESPERA DE PROVEEDOR] ──► Proveedor resuelve ──► [EN ATENCIÓN]
        │
        ├─► Necesita compra ──► [PENDIENTE DE COMPRA] ──► [PENDIENTE DE ENTREGA] ──► [EN ATENCIÓN]
        │
        │ Agente resuelve
        ▼
   [RESUELTO] ──► Correo al solicitante: "Tu ticket fue resuelto"
        │
        │ Confirmación
        ▼
   [CERRADO] ✓
```

### Flujo con autorización requerida

```
   [EN ATENCIÓN] o [ASIGNADO]
        │
        │ Requiere aprobación de dirección
        ▼
   [EN ESPERA DE AUTORIZACIÓN]
        │
        ├─► Dirección autoriza ──► [EN ATENCIÓN] ──► continúa flujo normal
        │
        └─► Dirección rechaza ──► [RECHAZADO] ──► Correo al solicitante
```

### Flujo de tarea interna

```
Administrador crea tarea interna
        │
        ▼
   [ASIGNADO] (inicia aquí directamente)
        │
        │ continúa flujo normal del agente...
        ▼
   [CERRADO] ✓  (sin correos al solicitante)
```

---

## 7. Catálogos del sistema

Los catálogos son la configuración base del sistema. Solo el **Administrador TI** tiene acceso.

### 7.1 Empresas

Empresas del Grupo Gonza que pueden registrar tickets.

| Campo | Descripción |
|---|---|
| Clave | Identificador corto (ej. `GG`, `TCS`) |
| Nombre | Nombre completo de la empresa |
| Activo | Si está activa aparece en el formulario público |

### 7.2 Departamentos

Áreas disponibles para clasificar al solicitante.

| Campo | Descripción |
|---|---|
| Nombre | Nombre del departamento |
| Activo | Si está activo aparece en el formulario público |

### 7.3 Categorías

Tipos de solicitud disponibles.

| Campo | Descripción |
|---|---|
| Nombre | Nombre de la categoría |
| Descripción | Explicación visible al usuario |
| Requiere autorización | Si está activo, el ticket iniciará en **En Espera de Autorización** automáticamente |
| Solo interno | Si está activo, **no aparece** en el formulario público — solo está disponible para tareas internas |
| Activo | Si está activo, está disponible para usarse |

### 7.4 Prioridades

Niveles de urgencia de los tickets.

| Campo | Descripción |
|---|---|
| Clave | Identificador corto (ej. `CRITICA`, `ALTA`) |
| Etiqueta | Nombre que ve el usuario |
| Descripción | Criterio de uso |
| SLA | Tiempo de respuesta objetivo (descriptivo) |
| Orden | Orden de aparición en el formulario |
| Activo | Si está activo, está disponible para seleccionarse |

### 7.5 Agentes TI

Usuarios del equipo de TI que pueden atender tickets.

| Campo | Descripción |
|---|---|
| Usuario Django | Cuenta de acceso al sistema |
| Activo | Si está activo, aparece disponible para asignación |

### Comportamiento al desactivar un registro

Al desactivar cualquier elemento de un catálogo:
- ✅ El registro **no se elimina** — el historial y trazabilidad se conservan
- ✅ Los tickets existentes que usaban ese elemento **no se afectan**
- ❌ El elemento **deja de aparecer** en formularios y selectores para nuevos tickets
- ✅ Se puede **reactivar** en cualquier momento

---

## 8. Aplicación Móvil (PWA)

El sistema incluye una aplicación web progresiva (PWA) optimizada para celular, destinada al equipo de TI.

### Instalación

**iPhone (Safari):**
1. Abre `https://ti.grupogonza.phanalytics.com.mx` en Safari
2. Toca el ícono de compartir (⬆)
3. Selecciona **"Añadir a la pantalla de inicio"**
4. Confirma con **"Añadir"**

**Android (Chrome):**
1. Abre la URL en Chrome
2. Toca el menú (⋮) y selecciona **"Instalar app"** o **"Añadir a pantalla de inicio"**

### Funcionalidades disponibles en móvil

| Función | Agente | Admin |
|---|---|---|
| Dashboard con KPIs personales | ✅ | — |
| Dashboard con KPIs globales del equipo | — | ✅ |
| Lista de tickets | ✅ | ✅ |
| Detalle del ticket con historial | ✅ | ✅ |
| Enviar mensajes y notas | ✅ | ✅ |
| Cambiar estatus | ✅ | ✅ |
| Asignar / reasignar agente | — | ✅ |
| Solicitar autorización | — | ✅ |
| Crear ticket nuevo (formulario público) | ✅ | — |
| Crear tarea interna 🔒 | — | ✅ |
| Reporte de productividad personal | ✅ | — |
| Reportes globales del equipo | — | ✅ |
| Cerrar sesión | ✅ | ✅ |

---

## 9. Notificaciones por correo

El sistema envía correos automáticos en los siguientes eventos:

| Evento | Destinatario | Contenido |
|---|---|---|
| Ticket creado | Solicitante | Folio, resumen y enlace de seguimiento |
| Ticket asignado | Solicitante | Nombre del agente asignado |
| Ticket asignado | Agente | Detalle del ticket y enlace al panel |
| Mensaje público enviado | Solicitante | Contenido del mensaje |
| Ticket resuelto | Solicitante | Confirmación con enlace para revisar |
| Ticket cerrado | Solicitante | Confirmación de cierre |

**Notas:**
- Las **notas internas** nunca se envían al solicitante
- Los tickets con `es_tarea_interna = True` (tareas internas) **no envían correos al solicitante**
- Los correos se envían desde: `TI Grupo Gonza <ti@phanalytics.com.mx>`

---

## 10. Glosario

| Término | Definición |
|---|---|
| **Ticket** | Registro de una solicitud o problema reportado al equipo de TI |
| **Folio** | Identificador único del ticket (ej. `TK-0042`) |
| **Agente TI** | Miembro del equipo de TI que atiende tickets |
| **Administrador TI** | Responsable del área de TI con acceso total al sistema |
| **Solicitante** | Colaborador que registra un ticket |
| **Estatus** | Estado actual del ticket dentro del flujo de atención |
| **SLA** | Acuerdo de nivel de servicio — tiempo de respuesta esperado según prioridad |
| **Nota interna** | Comentario visible solo para el equipo de TI |
| **Tarea interna** | Ticket creado por el admin TI para el equipo, sin solicitante externo |
| **Categoría interna** | Tipo de solicitud exclusivo para tareas internas, no visible en el formulario público |
| **Autorización** | Aprobación de dirección requerida para ejecutar ciertos cambios o adquisiciones |
| **PWA** | Progressive Web App — aplicación web instalable en el celular sin pasar por la App Store |
| **Token de seguimiento** | Enlace único y seguro que recibe el solicitante para ver su ticket sin necesidad de login |

---

*Sistema desarrollado por PHAnalytics para Grupo Gonza.*
*Soporte técnico: ipenuelas@phanalytics.com.mx*
