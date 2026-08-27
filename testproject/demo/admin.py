from django.contrib import admin

from .models import Attachment, Request, Settings, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'tax_code']
    search_fields = ['company_name', 'tax_code']


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ['title', 'supplier', 'budget', 'created_at']
    list_filter = ['supplier']
    search_fields = ['title', 'description']
    raw_id_fields = ['supplier']


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['description', 'request', 'uploaded_at']


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ['auto_approval_threshold', 'notification_email']
