import requests
from collections import OrderedDict
from django import forms
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SECRET_REDACTED, SettingsForm

from .csob_client import CSOBClient
from .fields import SecretKeySettingsTextareaField


class CSOBOrganizerSettingsForm(SettingsForm):
    payment_csob__enabled = forms.BooleanField(
        label=_("Enable ČSOB payments by default"),
        required=False,
    )
    payment_csob_merchant_id = forms.CharField(
        label=_("Merchant ID"),
        required=False,
    )
    payment_csob_private_key = SecretKeySettingsTextareaField(
        label=_("Private Merchant Key"),
        required=False,
    )
    payment_csob_public_key = SecretKeySettingsTextareaField(
        label=_("Public Bank Key"),
        required=False,
    )
    payment_csob_use_sandbox = forms.BooleanField(
        label=_("Use Sandbox"),
        required=False,
    )

    def clean(self):
        data = super().clean()
        for field in ("payment_csob_private_key", "payment_csob_public_key"):
            if data.get(field) == SECRET_REDACTED:
                data[field] = self.initial.get(field)

        if not data.get("payment_csob__enabled"):
            return data

        required_fields = [
            "payment_csob_merchant_id",
            "payment_csob_private_key",
            "payment_csob_public_key",
        ]
        for field in required_fields:
            if not data.get(field):
                self.add_error(field, _("This field is required."))

        if self.errors:
            return data

        if not self._validate_keys(
            data["payment_csob_merchant_id"],
            data["payment_csob_private_key"],
            data["payment_csob_public_key"],
            data.get("payment_csob_use_sandbox", False),
        ):
            raise forms.ValidationError(
                _("The keys you provided are not valid. Please verify the keys and try again.")
            )

        return data

    def _validate_keys(self, merchant_id, private_key, public_key, use_sandbox):
        try:
            client = CSOBClient(
                private_key,
                public_key,
                merchant_id,
                use_sandbox,
            )
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
