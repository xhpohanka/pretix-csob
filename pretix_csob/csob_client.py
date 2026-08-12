import requests
import urllib.parse
import logging
import json
from base64 import b64decode as base64_decode, b64encode as base64_encode
from collections import OrderedDict
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5


REQUEST_TIMEOUT = 15
logger = logging.getLogger("pretix.plugins.csob")


class CSOBClient:
    @staticmethod
    def extract_data(data: OrderedDict | list) -> list:
        """
        Extracts values from a dictionary recursively
        :param data: The dictionary to extract values from
        :return: List of values
        """
        if isinstance(data, list):
            return data

        values = []

        def _extract(d):
            for value in d.values():
                if isinstance(value, dict):
                    _extract(value)
                elif isinstance(value, list):
                    for v in value:
                        _extract(v)
                else:
                    if isinstance(value, bool):
                        values.append(str(value).lower())
                    else:
                        values.append(str(value))

        _extract(data)

        return values

    @staticmethod
    def get_current_timestamp():
        from datetime import datetime

        return datetime.now().strftime("%Y%m%d%H%M%S")

    def __init__(
        self,
        private_key: str,
        public_key: str,
        merchant_id: str,
        sandbox: bool,
    ):
        """
        Constructor for the CSOBClient class.

        :param private_key: The merchant private key.
        :param public_key: The bank public key.
        :param sandbox: Whether to use the sandbox environment.
        """
        self._private_key = private_key
        self._public_key = public_key
        self._merchant_id = merchant_id
        self._sandbox = sandbox

        if not self._private_key or not self._public_key:
            raise ValueError("Invalid private or public key")

    @property
    def merchant_id(self):
        return self._merchant_id

    def get(self, endpoint: str, data: list = None) -> requests.Response:
        signature = self._sign_data(data)
        url = (
            self.get_api_url(endpoint)
            + ("" if endpoint.endswith("/") else "/")
            + "/".join([urllib.parse.quote_plus(v) for v in data])
            + f"/{urllib.parse.quote_plus(signature)}"
        )

        request = requests.get(url, timeout=REQUEST_TIMEOUT)
        response = OrderedDict(request.json())

        if request.status_code >= 400 and "signature" not in response:
            logger.warning("CSOB returned an unsigned error response: %s", response)
            return request

        verified = self._verify_data(response)

        if not verified:
            logger.warning("CSOB response signature verification failed: %s", response)
            raise ValueError("Invalid response signature")

        return request

    def post(self, endpoint: str, data: OrderedDict = None) -> requests.Response:
        signature = self._sign_data(data)
        url = self.get_api_url(endpoint)

        request_data = OrderedDict(
            {
                **data,
                "signature": signature,
            }
        )

        logger.debug(
            "CSOB POST %s request JSON with signature: %s",
            endpoint,
            json.dumps(request_data, ensure_ascii=False),
        )
        request = requests.post(url, json=request_data, timeout=REQUEST_TIMEOUT)
        response = OrderedDict(request.json())

        if request.status_code >= 400 and "signature" not in response:
            logger.warning("CSOB returned an unsigned error response: %s", response)
            return request

        verified = self._verify_data(response)

        if not verified:
            logger.warning("CSOB response signature verification failed: %s", response)
            raise ValueError("Invalid response signature")

        return request

    def _sign_data(self, data: OrderedDict | list, base64=True) -> str:
        values = self.extract_data(data)
        logger.debug("CSOB signing values: %s", "|".join(values))

        h = SHA256.new("|".join(values).encode("utf-8"))
        key = RSA.importKey(self._private_key)
        signature = PKCS1_v1_5.new(key).sign(h)

        return base64_encode(signature).decode("utf-8") if base64 else h.hexdigest()

    def _verify_data(self, data: OrderedDict) -> bool:
        signature = data.pop("signature", None)

        if not signature or not self._public_key:
            return False

        try:
            data.move_to_end("dttm", last=False)
            data.move_to_end("payId", last=False)
        except KeyError:
            pass

        values = self.extract_data(data)

        h = SHA256.new("|".join(values).encode("utf-8"))
        public_key: RSA.RsaKey = RSA.importKey(self._public_key)
        signer = PKCS1_v1_5.new(public_key)
        return signer.verify(h, base64_decode(signature))

    def get_api_url(self, endpoint=""):
        base_url = (
            "https://iapi.iplatebnibrana.csob.cz/api/v1.9/"
            if self._sandbox
            else "https://api.platebnibrana.csob.cz/api/v1.9/"
        )
        return base_url + endpoint
