from collections import OrderedDict
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django_scopes import scopes_disabled
from pretix.base.models import Order
from pretix.multidomain.urlreverse import eventreverse

from pretix_csob.csob_client import CSOBClient
from pretix_csob.csob_payment import CSOBOrderPayment
from pretix_csob.payment import CSOBMethod


@csrf_exempt
@scopes_disabled()
def csob_return_view(request, order, payment, secret):
    order = get_object_or_404(Order, code=order)
    payment: CSOBOrderPayment = get_object_or_404(CSOBOrderPayment, pk=payment, order=order)

    provider: CSOBMethod = payment.payment_provider

    if secret != provider._get_payment_secret(payment):
        return HttpResponseBadRequest("Invalid secret")

    client = CSOBClient(
        provider.settings.get("private_key"),
        provider.settings.get("public_key"),
        provider.settings.get("merchant_id"),
        provider.settings.get("use_sandbox"),
    )

    verified = client._verify_data(OrderedDict(request.POST))

    status_request = client.get(
        "payment/status",
        [
            provider.settings.get("merchant_id"),
            payment.pay_id,
            client.get_current_timestamp(),
        ],
    )

    status_response = status_request.json()

    result = request.POST.get("resultCode")
    payment_state = status_response.get("paymentStatus")
    payment_state_detail = status_response.get("statusDetail")

    if verified and result == "0":
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
def csob_check_status(request, order, payment, secret):
    order: Order = get_object_or_404(Order, code=order)
    payment: CSOBOrderPayment = get_object_or_404(CSOBOrderPayment, pk=payment, order=order)
    provider: CSOBMethod = payment.payment_provider

    if secret != provider._get_payment_secret(payment):
        return HttpResponseBadRequest("Invalid secret")

    client = CSOBClient(
        provider.settings.get("private_key"),
        provider.settings.get("public_key"),
        provider.settings.get("merchant_id"),
        provider.settings.get("use_sandbox"),
    )

    status_request = client.get(
        "payment/status",
        [
            provider.settings.get("merchant_id"),
            payment.pay_id,
            client.get_current_timestamp(),
        ],
    )

    status_response = status_request.json()

    result = status_response.get("resultCode")
    payment_state = status_response.get("paymentStatus")
    payment_state_detail = status_response.get("statusDetail")

    if result == "0":
        payment.update_state(int(payment_state), payment_state_detail)
    else:
        payment.fail({"error": "Payment failed with error code {}".format(result)})

    return redirect(
        eventreverse(
            order.event,
            "presale:event.order",
            kwargs={"order": order.code, "secret": order.secret},
        )
    )
