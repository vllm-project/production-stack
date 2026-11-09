import socket

import aiohttp
import pytest
from aiohttp import web

from vllm_router.aiohttp_client import AiohttpClientWrapper


async def test_backend_reachable_after_a_failed_lookup(monkeypatch):
    # A backend created after the router's first lookup must be reachable once
    # the system resolver answers. aiohttp's default resolver with aiodns,
    # c-ares, never consults getaddrinfo and caches the failure in-process.
    async def health(request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://vllm-worker.invalid:{runner.addresses[0][1]}/health"

        real_getaddrinfo = socket.getaddrinfo
        service_exists = False

        def getaddrinfo(host, *args, **kwargs):
            if host == "vllm-worker.invalid":
                if not service_exists:
                    raise socket.gaierror(
                        socket.EAI_NONAME, "Name or service not known"
                    )
                host = "127.0.0.1"
            return real_getaddrinfo(host, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        wrapper = AiohttpClientWrapper()
        wrapper.start()
        try:
            with pytest.raises(aiohttp.ClientConnectorDNSError):
                async with wrapper().get(url):
                    pass

            service_exists = True
            async with wrapper().get(url) as response:
                assert response.status == 200
        finally:
            await wrapper.stop()
    finally:
        await runner.cleanup()
