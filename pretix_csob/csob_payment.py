import json
from json import JSONDecodeError
from pretix.base.models import OrderPayment


class CSOBOrderPayment(OrderPayment):
    class Meta:
        proxy = True

    def _get_info_data(self):
        if not self.info:
            return {}
        try:
            return json.loads(self.info)
        except JSONDecodeError:
            return {}

    @property
    def pay_id(self):
        return self._get_info_data().get("payId")

    @pay_id.setter
    def pay_id(self, value):
        info_data = self._get_info_data()
        info_data["payId"] = value
        self.info = json.dumps(info_data)

    @property
    def csob_testmode(self):
        return self._get_info_data().get("csob_testmode")

    @csob_testmode.setter
    def csob_testmode(self, value):
        info_data = self._get_info_data()
        info_data["csob_testmode"] = value
        self.info = json.dumps(info_data)

    def update_state(self, payment_status: int, detail: str):
        if payment_status == 1:
            self.state = self.PAYMENT_STATE_CREATED
        elif payment_status in [2, 4]:
            self.state = self.PAYMENT_STATE_PENDING
        elif payment_status in [3, 5, 6]:
            pay_id = self.pay_id
            self.order.comment = f"ČSOB payment {pay_id} failed: {detail}"
            self.order.save()

            self.fail(
                info={
                    **self._get_info_data(),
                    "payId": pay_id,
                    "error": detail,
                },
            )
            return
        elif payment_status in [7, 8]:
            self.confirm()
            return

        self.save()
