import requests
from collections import OrderedDict
from django import forms
from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SECRET_REDACTED
from pretix.base.signals import register_global_settings, register_payment_providers
from pretix.control.signals import nav_organizer

from .csob_client import CSOBClient
from .fields import SecretKeySettingsTextareaField


class CSOBKeysValidator:
    def __init__(self, merchant_id: str, initial_private: str, initial_public: str, type: str):
        self._merchant_id = merchant_id
        self._initial_private = initial_private
        self._initial_public = initial_public
        self._type = type

    def __call__(self, value):
        merchant_id = (
            (value if value != SECRET_REDACTED else self._merchant_id)
            if self._type == "merchant_id"
            else self._merchant_id
        )
        private_key = (
            (value if value != SECRET_REDACTED else self._initial_private)
            if self._type == "private"
            else self._initial_private
        )
        public_key = (
            (value if value != SECRET_REDACTED else self._initial_public)
            if self._type == "public"
            else self._initial_public
        )

        if not private_key or not public_key or not merchant_id:
            return True

        try:
            client = CSOBClient(private_key, public_key, merchant_id, True)
            echo_get_request = client.get("echo", [merchant_id, client.get_current_timestamp()])
            echo_get_data = echo_get_request.json()
            if echo_get_request.status_code != 200 or echo_get_data.get("resultCode") != 0:
                return False

            echo_post_request = client.post(
                "echo",
                OrderedDict(
                    {
                        "merchantId": merchant_id,
                        "dttm": client.get_current_timestamp(),
                    }
                ),
            )
            echo_post_data = echo_post_request.json()
            if echo_post_request.status_code != 200 or echo_post_data.get("resultCode") != 0:
                return False

            return True
        except ValueError:
            return False
        except requests.RequestException:
            return False


@receiver(register_payment_providers, dispatch_uid="payment_csob")
def register_payment_provider(sender, **kwargs):
    from .payment import CSOBMethod, CSOBSettingsHolder

    return [CSOBSettingsHolder, CSOBMethod]


@receiver(register_global_settings, dispatch_uid="csob_global_settings")
def register_global_settings(sender, **kwargs):
    return OrderedDict(
        [
            (
                "payment_csob_merchant_id",
                forms.CharField(
                    label=_("ČSOB: Merchant ID (live)"),
                    required=False,
                ),
            ),
            (
                "payment_csob_private_key",
                SecretKeySettingsTextareaField(
                    label=_("ČSOB: Private Merchant Key (live)"),
                    required=False,
                ),
            ),
            (
                "payment_csob_public_key",
                SecretKeySettingsTextareaField(
                    label=_("ČSOB: Public Bank Key (live)"),
                    required=False,
                ),
            ),
            (
                "payment_csob_test_merchant_id",
                forms.CharField(
                    label=_("ČSOB: Merchant ID (sandbox)"),
                    required=False,
                ),
            ),
            (
                "payment_csob_test_private_key",
                SecretKeySettingsTextareaField(
                    label=_("ČSOB: Private Merchant Key (sandbox)"),
                    required=False,
                ),
            ),
            (
                "payment_csob_test_public_key",
                SecretKeySettingsTextareaField(
                    label=_("ČSOB: Public Bank Key (sandbox)"),
                    required=False,
                ),
            ),
        ]
    )


@receiver(nav_organizer, dispatch_uid="csob_nav_organizer")
def nav_organizer_settings(sender, request, organizer, **kwargs):
    if not request.user.has_organizer_permission(
        organizer, "organizer.settings.general:write", request=request
    ):
        return []

    url = resolve(request.path_info)
    return [
        {
            "label": _("ČSOB"),
            "url": reverse(
                "plugins:pretix_csob:settings",
                kwargs={
                    "organizer": organizer.slug,
                },
            ),
            "parent": reverse(
                "control:organizer.edit",
                kwargs={
                    "organizer": organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_csob"
            and url.url_name == "settings",
        }
    ]
