from django.urls import path

from .views import csob_check_status, csob_return_view

event_patterns = [
    path(
        "csob/return/<str:order>/<int:payment>/<str:secret>/",
        csob_return_view,
        name="return",
    ),
    path(
        "csob/check_status/<str:order>/<int:payment>/<str:secret>/",
        csob_check_status,
        name="check_status",
    ),
]
