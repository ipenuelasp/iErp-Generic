from django.contrib import admin
from .models import Doctor, Hospital, SolicitudCirugia


@admin.register(Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo', 'ciudad', 'empresa', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre', 'codigo')


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'rfc', 'telefono', 'empresa', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre', 'rfc')


@admin.register(SolicitudCirugia)
class SolicitudCirugiaAdmin(admin.ModelAdmin):
    list_display = ('folio', 'paciente', 'doctor', 'hospital', 'fecha_cirugia', 'estado')
    list_filter = ('empresa', 'estado')
    search_fields = ('folio', 'paciente')
