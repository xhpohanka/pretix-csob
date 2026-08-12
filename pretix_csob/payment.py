import requests
import urllib.parse
from collections import OrderedDict
from decimal import Decimal
from django import forms
from django.db import transaction
from django.http import HttpRequest
from django.template.loader import get_template, render_to_string
from django.urls import resolve
from django.utils.translation import gettext as __, gettext_lazy as _
from pretix.base.forms import SECRET_REDACTED
from pretix.base.models import Event, Order, OrderPayment
from pretix.base.payment import BasePaymentProvider, PaymentException, logger
from pretix.base.settings import SettingsSandbox
from pretix.helpers import OF_SELF
from pretix.multidomain.urlreverse import build_absolute_uri, eventreverse

from .csob_client import CSOBClient
from .csob_payment import CSOBOrderPayment
from .fields import SecretKeySettingsTextareaField


class CSOBSettingsHolder(BasePaymentProvider):
    identifier = "csob_settings"
    verbose_name = _("ČSOB")
    is_enabled = False
    is_meta = True

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox("payment", "csob", event)

    def settings_form_clean(self, data):
        merchant_id = data.get("payment_csob_merchant_id")
        use_sandbox = data.get("payment_csob_use_sandbox")
        private_key = (
            data.get("payment_csob_private_key")
            if data.get("payment_csob_private_key") != SECRET_REDACTED
            else self.settings.get("private_key")
        )
        public_key = (
            data.get("payment_csob_public_key")
            if data.get("payment_csob_public_key") != SECRET_REDACTED
            else self.settings.get("public_key")
        )

        if use_sandbox is None:
            use_sandbox = self.settings.get("use_sandbox", as_type=bool)

        if not merchant_id or not private_key or not public_key:
            return {
                **data,
                "payment_csob_merchant_id": merchant_id,
                "payment_csob_private_key": private_key,
                "payment_csob_public_key": public_key,
                "payment_csob_use_sandbox": use_sandbox,
            }

        if not self._validate_keys(merchant_id, private_key, public_key, use_sandbox):
            raise forms.ValidationError(
                _("The keys you provided are not valid. Please verify the keys and try again.")
            )

        return {
            **data,
            "payment_csob_merchant_id": merchant_id,
            "payment_csob_private_key": private_key,
            "payment_csob_public_key": public_key,
            "payment_csob_use_sandbox": use_sandbox,
        }

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

    @property
    def settings_form_fields(self):
        fields = [
            (
                "merchant_id",
                forms.CharField(
                    label=_("Merchant ID"),
                    help_text=_("Your ČSOB Merchant ID."),
                    required=True,
                ),
            ),
            (
                "private_key",
                SecretKeySettingsTextareaField(
                    label=_("Private Merchant Key"),
                    required=True,
                ),
            ),
            (
                "public_key",
                SecretKeySettingsTextareaField(
                    label=_("Public Bank Key"),
                    required=True,
                ),
            ),
            (
                "use_sandbox",
                forms.BooleanField(
                    label=_("Use Sandbox"),
                    required=False,
                ),
            ),
        ]

        d = OrderedDict(fields + list(super().settings_form_fields.items()))

        return d


class CSOBMethod(BasePaymentProvider):
    identifier = "csob"
    verbose_name = _("ČSOB")
    public_name = _("ČSOB")
    execute_payment_needs_user = True
    method = "card"

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox("payment", "csob", event)

    @property
    def settings_form_fields(self):
        return {}

    @property
    def is_enabled(self):
        return super().is_enabled and bool(
            self.settings.merchant_id
            and self.settings.private_key
            and self.settings.public_key
        )

    def is_implicit(self, request: HttpRequest) -> bool:
        enabled_providers = []
        for provider in request.event.get_payment_providers().values():
            if provider.is_meta or not provider.is_enabled:
                continue
            enabled_providers.append(provider.identifier)

        return enabled_providers == [self.identifier]

    def payment_prepare(self, request, payment):
        return self.payment_is_valid_session(request)

    def payment_form_render(self, request: HttpRequest, total: Decimal, order: Order = None) -> str:
        return _("Use ČSOB payment gateway")

    def payment_pending_render(self, request, payment):
        check_url = eventreverse(
            self.event,
            "plugins:pretix_csob:check_status",
            kwargs={
                "order": payment.order.code,
                "payment": payment.pk,
                "secret": self._get_payment_secret(payment),
            },
        )

        context = {
            "order": payment.order,
            "payment": payment,
            "check_url": check_url,
            "csrf_token": request.COOKIES.get("pretix_csrftoken", ""),
            "_": _,
        }

        return render_to_string(
            "pretix_csob/payment_pending.html", context=context, request=request
        )

    def payment_control_render(self, request, payment):
        return _("Payment status: {}").format(payment.state)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        ex = None
        with transaction.atomic():
            try:
                return self._execute_payment(request, payment)
            except PaymentException as e:
                ex = e
        if ex:
            raise ex

        return False

    def _execute_payment(self, request: HttpRequest, payment: OrderPayment):
        payment: CSOBOrderPayment = CSOBOrderPayment.objects.select_for_update(of=OF_SELF).get(
            pk=payment.pk
        )

        if payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED:
            logger.warning(
                "payment is already confirmed; possible return-view/webhook race-condition"
            )
            return

        if not self.is_enabled:
            payment.fail(info={"error": "ČSOB payment provider is not configured."})
            raise PaymentException(_("This payment provider is not configured correctly."))

        currency = payment.order.event.currency
        custom_id = str(payment.pk)

        try:
            client = CSOBClient(
                self.settings.private_key,
                self.settings.public_key,
                self.settings.merchant_id,
                self.settings.get("use_sandbox", as_type=bool),
            )
            total_amount = int(payment.amount * 100)

            cart_item = OrderedDict(
                {
                    "name": "Tickets",
                    "quantity": 1,
                    "amount": total_amount,
                }
            )

            payment_data = OrderedDict(
                {
                    "merchantId": self.settings.merchant_id,
                    "orderNo": custom_id,
                    "dttm": self._get_current_timestamp(),
                    "payOperation": "payment",
                    "payMethod": "card",
                    "totalAmount": total_amount,
                    "currency": currency,
                    "closePayment": True,
                    "returnUrl": build_absolute_uri(
                        self.event,
                        "plugins:pretix_csob:return",
                        kwargs={
                            "order": payment.order.code,
                            "payment": payment.pk,
                            "secret": self._get_payment_secret(payment),
                        },
                    ),
                    "returnMethod": "POST",
                    "cart": [cart_item],
                    "language": self._get_language_code(request),
                }
            )

            init_request = client.post("payment/init", payment_data)
            init_response: dict = init_request.json()

            pay_id = init_response.get("payId")

            if init_request.status_code != 200 or init_response.get("resultCode") != 0:
                logger.error("ČSOB payment initiation error: %s", init_response)
                payment.fail(
                    info={
                        "error": "An error occurred while communicating with the payment gateway."
                    }
                )
                raise PaymentException(
                    "An error occurred while communicating with the payment gateway."
                )

            payment.order.comment = "Order in POS Merchant: {}".format(pay_id)
            payment.order.save()

            payment.pay_id = pay_id
            payment.save()

            process_data = OrderedDict(
                {
                    "merchantId": payment_data.get("merchantId"),
                    "payId": payment.pay_id,
                    "dttm": self._get_current_timestamp(),
                }
            )

            process_signature = client._sign_data(process_data)

            return client.get_api_url("payment/process/{}/{}/{}/{}/").format(
                process_data.get("merchantId"),
                urllib.parse.quote_plus(payment.pay_id),
                process_data.get("dttm"),
                urllib.parse.quote_plus(process_signature),
            )

        except ValueError:
            logger.exception("ČSOB payment initiation error")
            payment.fail(
                info={"error": "An error occurred while communicating with the payment gateway."}
            )
            raise PaymentException(
                "An error occurred while communicating with the payment gateway."
            )

        except requests.RequestException:
            logger.exception("ČSOB payment initiation error")
            payment.fail(
                info={"error": "An error occurred while communicating with the payment gateway."}
            )
            raise PaymentException(
                "An error occurred while communicating with the payment gateway."
            )

    def checkout_confirm_render(self, request) -> str:
        """
        Returns the HTML that should be displayed when the user selected this provider
        on the 'confirm order' page.
        """
        template = get_template("pretix_csob/checkout_payment_confirm.html")
        ctx = {
            "request": request,
            "url": resolve(request.path_info),
            "event": self.event,
            "settings": self.settings,
            "method": self.method,
        }
        return template.render(ctx)

    def _get_current_timestamp(self):
        from datetime import datetime

        return datetime.now().strftime("%Y%m%d%H%M%S")

    def _get_language_code(self, request):
        language = request.LANGUAGE_CODE.lower().split("-")[0]
        return language if language in {"cs", "en", "de", "sk", "hu", "pl", "ro"} else "en"

    def _get_payment_secret(self, payment: OrderPayment) -> str:
        client = CSOBClient(
            self.settings.private_key,
            self.settings.public_key,
            self.settings.merchant_id,
            self.settings.get("use_sandbox", as_type=bool),
        )

        payment_data = OrderedDict(
            {
                "pk": payment.pk,
                "order": payment.order.pk,
                "amount": str(payment.amount),
            }
        )
        return client._sign_data(payment_data, False)

    def payment_is_valid_session(self, request):
        return True
