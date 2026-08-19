from collections import OrderedDict
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from django.views.decorators.csrf import csrf_exempt
from django_scopes import scopes_disabled
from pretix.base.models import Organizer
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin
from pretix.helpers.http import redirect_to_url
from pretix.multidomain.urlreverse import eventreverse

from pretix_csob.csob_payment import CSOBOrderPayment
from pretix_csob.forms import CSOBOrganizerSettingsForm
from pretix_csob.payment import CSOBMethod


def _get_order(request, code):
    try:
        return request.event.orders.get(code=code)
    except request.event.orders.model.DoesNotExist:
        raise Http404("Unknown order")


def _result_is_success(result):
    return str(result) == "0"


@csrf_exempt
@scopes_disabled()
def csob_return_view(request, order, payment, secret, *args, **kwargs):
    order = _get_order(request, order)
    payment: CSOBOrderPayment = get_object_or_404(CSOBOrderPayment, pk=payment, order=order)

    provider: CSOBMethod = payment.payment_provider

    if secret != provider._get_payment_secret(payment):
        return HttpResponseBadRequest("Invalid secret")

    client = provider._client(payment=payment)

    response_data = request.POST if request.method == "POST" else request.GET
    verified = client._verify_data(OrderedDict(response_data.items()))

    status_request = client.get(
        "payment/status",
        [
            client.merchant_id,
            payment.pay_id,
            client.get_current_timestamp(),
        ],
    )

    status_response = status_request.json()

    result = response_data.get("resultCode")
    payment_state = status_response.get("paymentStatus")
    payment_state_detail = status_response.get("statusDetail")

    if verified and _result_is_success(result):
        payment.update_state(int(payment_state), payment_state_detail)
    else:
        payment.fail(info={"error": "Payment failed with error code {}".format(result)})

    return redirect(
        eventreverse(
            order.event,
            "presale:event.order",
            kwargs={"order": order.code, "secret": order.secret},
        )
    )


@scopes_disabled()
def csob_check_status(request, order, payment, secret, *args, **kwargs):
    order = _get_order(request, order)
    payment: CSOBOrderPayment = get_object_or_404(CSOBOrderPayment, pk=payment, order=order)
    provider: CSOBMethod = payment.payment_provider

    if secret != provider._get_payment_secret(payment):
        return HttpResponseBadRequest("Invalid secret")

    client = provider._client(payment=payment)

    status_request = client.get(
        "payment/status",
        [
            client.merchant_id,
            payment.pay_id,
            client.get_current_timestamp(),
        ],
    )

    status_response = status_request.json()

    result = status_response.get("resultCode")
    payment_state = status_response.get("paymentStatus")
    payment_state_detail = status_response.get("statusDetail")

    if _result_is_success(result):
        payment.update_state(int(payment_state), payment_state_detail)
    else:
        payment.fail(info={"error": "Payment failed with error code {}".format(result)})

    return redirect(
        eventreverse(
            order.event,
            "presale:event.order",
            kwargs={"order": order.code, "secret": order.secret},
        )
    )


class CSOBOrganizerSettingsFormView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, FormView
):
    model = Organizer
    permission = "organizer.settings.general:write"
    form_class = CSOBOrganizerSettingsForm
    template_name = "pretix_csob/organizer_settings.html"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_csob:settings",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.organizer
        return kwargs

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            if form.has_changed():
                self.request.organizer.log_action(
                    "pretix.organizer.settings",
                    user=self.request.user,
                    data={k: form.cleaned_data.get(k) for k in form.changed_data},
                )
            messages.success(self.request, _("Your changes have been saved."))
            return redirect_to_url(self.get_success_url())
        else:
            messages.error(
                self.request, _("We could not save your changes. See below for details.")
            )
            return self.get(request)
