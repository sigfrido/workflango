from django.urls import path

from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),

    # Impersonation (admin only)
    path('impersonate/', views.ImpersonateStartView.as_view(), name='impersonate_start'),
    path('impersonate/stop/', views.ImpersonateStopView.as_view(), name='impersonate_stop'),

    # Suppliers
    path('suppliers/', views.SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/new/', views.SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/', views.SupplierDetailView.as_view(), name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_edit'),
    path('suppliers/<int:pk>/history/', views.SupplierHistoryView.as_view(), name='supplier_history'),
    path(
        'suppliers/<int:pk>/change-state/<str:nuovo_stato>/',
        views.SupplierChangeStateView.as_view(), name='supplier_change_state',
    ),

    # Requests
    path('requests/', views.RequestListView.as_view(), name='request_list'),
    path('requests/new/', views.RequestCreateView.as_view(), name='request_create'),
    path('requests/<int:pk>/', views.RequestDetailView.as_view(), name='request_detail'),
    path('requests/<int:pk>/edit/', views.RequestUpdateView.as_view(), name='request_edit'),
    path('requests/<int:pk>/history/', views.RequestHistoryView.as_view(), name='request_history'),
    path(
        'requests/<int:pk>/change-state/<str:nuovo_stato>/',
        views.RequestChangeStateView.as_view(), name='request_change_state',
    ),

    # Attachments (tied to a Request)
    path('requests/<int:request_pk>/attachments/new/', views.AttachmentCreateView.as_view(), name='attachment_create'),
    path('attachments/<int:pk>/delete/', views.AttachmentDeleteView.as_view(), name='attachment_delete'),

    # Settings (superuser only, singleton)
    path('settings/', views.SettingsView.as_view(), name='settings'),
]
