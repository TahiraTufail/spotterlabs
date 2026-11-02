import threading

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    name = "routing"

    def ready(self):
        from stations.cities import _load_index

        # Load the offline city index in the background so the first request does not pay for it.
        threading.Thread(target=_load_index, daemon=True).start()
