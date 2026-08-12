import json
from json import JSONDecodeError
from pretix.base.models import OrderPayment


class CSOBOrderPayment(OrderPayment):
    class Meta:
        proxy = True

    @property
    def pay_id(self):
        if not self.info:
            return None
        try:
            info_data = json.loads(self.info)
            return info_data.get("payId")
        except JSONDecodeError:
            return None

    @pay_id.setter
    def pay_id(self, value):
        info_data = {}
        if self.info:
            try:
                info_data = json.loads(self.info)
            except ValueError:
                info_data = {}

        info_data["payId"] = value
        self.info = json.dumps(info_data)

    def update_state(self, payment_status: int, detail: str):
        if payment_status == 1:
            self.state = self.PAYMENT_STATE_CREATED
        if payment_status in [2, 4]:
            self.state = self.PAYMENT_STATE_PENDING
        if payment_status == [3, 5, 6]:
            pay_id = self.pay_id
            self.order.comment = f"ČSOB payment {pay_id} failed: {detail}"
            self.order.save()

            self.fail(
                info=detail,
            )
        if payment_status in [7, 8]:
            self.confirm()

        self.save()
