from mapadroid.plugins.endpoints.AbstractPluginEndpoint import AbstractPluginEndpoint
import aiohttp_jinja2


class eventwatcherEndpoint(AbstractPluginEndpoint):
    """
    "/eventwatcher"
    """

    # TODO: Auth
    @aiohttp_jinja2.template('eventwatcher.html')
    async def get(self):
        return {"header": "eventwatcher",
                "title": "eventwatcher"}
