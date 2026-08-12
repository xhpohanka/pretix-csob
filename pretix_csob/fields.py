from django import forms
from pretix.base.forms import SECRET_REDACTED


class SecretKeySettingsTextareaWidget(forms.Textarea):
    def __init__(self, attrs=None):
        if attrs is None:
            attrs = {}
        attrs.update({"autocomplete": "new-password"})
        self.__reflect_value = False
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        self.__reflect_value = value and value != SECRET_REDACTED
        return value

    def get_context(self, name, value, attrs):
        if value and not self.__reflect_value:
            value = SECRET_REDACTED
        return super().get_context(name, value, attrs)


class SecretKeySettingsTextareaField(forms.CharField):
    widget = SecretKeySettingsTextareaWidget

    def has_changed(self, initial, data):
        if data == SECRET_REDACTED:
            return False
        return super().has_changed(initial, data)

    def run_validators(self, value):
        if value == SECRET_REDACTED:
            return
        return super().run_validators(value)
