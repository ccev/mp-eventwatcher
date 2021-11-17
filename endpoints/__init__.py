from aiohttp import web
import importlib
eventwatcherEndpoint = importlib.import_module("plugins.mp-eventwatcher.endpoints.eventwatcherEndpoint").eventwatcherEndpoint


def register_custom_plugin_endpoints(app: web.Application):
    # Simply register any endpoints here. If you do not intend to add any views (which is discouraged) simply "pass"
    app.router.add_view('/eventwatcher', eventwatcherEndpoint, name='eventwatcher')
