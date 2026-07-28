# Módulo de Tareas y Proyectos — documentación de diseño

Archivos de referencia generados en otra sesión (design + handoff técnico):

- `HANDOFF_modulo_tareas.html` — especificación técnica completa (modelo de datos, DDL,
  modelos Django, reglas de negocio, permisos, adjuntos, plan de implementación).
- `mockup_modulo_tareas.html` — mockup visual aprobado: Lista / Cronograma (Gantt) / Tablero
  (kanban) + panel de detalle de tarea. Referencia visual vinculante.
- `mockup_instanciar_plantilla.html` — asistente de 3 pasos para instanciar una plantilla.

## Ojo: el handoff es genérico y asume cosas que NO son de este repo

El propio handoff dice "gana el repo". Diferencias a adaptar cuando se construya:

| Handoff asume | Este repo (real) |
|---|---|
| Django 4.2 | Django 5.2 |
| `admon_sistema.Empresa` | `admon_empresas.Empresa` |
| `TenantModel` / `ClienteSaaS` | `TenantMiddleware` + FK `empresa` a mano; no hay `TenantModel` base |
| django-unfold admin | dashboard propio (templates Tailwind v2.0), sin unfold |
| DRF (API REST) | vistas server-rendered (class-based `View` + templates), no DRF |
| `GroupRequiredMixin` / `StaffRequiredMixin` | `LoginRequiredMixin` + sistema de módulos (`admon_empresas/modulos.py`) |

## Integración con este ERP

- Es un **módulo contratable extra**: alta en `admon_empresas/modulos.py` (MODULOS + SECCIONES),
  gating por `EmpresaModulo` (empresa contrata) ∩ `AccesoModuloUsuario` (usuario ve).
- Look & feel: seguir el estilo v2.0 (ver memoria del proyecto), no los templates del mockup tal cual
  (el mockup usa Inter/paleta índigo propia; el ERP usa su dashboard).
- Adjuntos: modelo genérico `comunes.Adjunto` con `GenericForeignKey` (reutilizable por todo el ERP).
- Nombres reservados: el contenedor se llama **`Tablero`**, NO `Proyecto` (choca con "obra" en otro sistema).

## Estado

Solo documentación por ahora. La construcción se hará por fases, primero en **staging**.
