from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_csob"
    verbose_name = "ČSOB plugin"

    class PretixPluginMeta:
        name = gettext_lazy("ČSOB plugin")
        author = "Inuits"
        description = gettext_lazy("ČSOB payment gateway plugin for pretix.")
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA
