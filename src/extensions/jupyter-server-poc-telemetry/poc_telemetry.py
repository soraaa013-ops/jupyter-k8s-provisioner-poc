import json
import os
import urllib.error
import urllib.request

from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
from tornado import web


class TelemetryHandler(APIHandler):
    @web.authenticated
    async def post(self):
        try:
            payload = json.loads(self.request.body)
            request = urllib.request.Request(
                os.environ.get("UEM_COLLECTOR_URL", "http://uem-collector:8080/v1/uem/events"),
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {os.environ['UEM_COLLECTOR_TOKEN']}",
                         "Content-Type": "application/json",
                         "X-Trace-Id": payload.get("trace_id", "lab")},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.set_status(response.status)
                self.finish(response.read())
        except urllib.error.HTTPError as error:
            self.set_status(error.code)
            self.finish(error.read())
        except Exception:
            self.log.exception("UEM forwarding failed")
            self.set_status(503)
            self.finish({"accepted": False})


def _load_jupyter_server_extension(server_app):
    route = url_path_join(server_app.web_app.settings["base_url"], "platform", "telemetry")
    server_app.web_app.add_handlers(".*$", [(route, TelemetryHandler)])


def _jupyter_server_extension_points():
    return [{"module": "poc_telemetry"}]
