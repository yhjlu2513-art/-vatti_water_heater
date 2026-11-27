"""API 客户端测试：本地起一个假云端，校验请求结构与错误映射。"""

from __future__ import annotations

import json

import pytest
from aiohttp import ClientSession, web

from custom_components.vatti_water_heater import api as api_module
from custom_components.vatti_water_heater.api import VattiClient
from custom_components.vatti_water_heater.exceptions import (
    VattiApiError,
    VattiAuthError,
    VattiDeviceOfflineError,
)
from custom_components.vatti_water_heater.models import CaptchaTicket

pytestmark = pytest.mark.enable_socket


class FakeCloud:
    """记录请求并按路径返回预设响应。"""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.responses: dict[str, dict] = {}
        self.runner: web.AppRunner | None = None
        self.base = ""

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/{tail:.*}", self._handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.base = f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    async def _handle(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.requests.append((request.path, body))
        payload = self.responses.get(request.path, {"code": 200, "data": None})
        return web.json_response(payload)


@pytest.fixture
async def cloud(monkeypatch):
    fake = FakeCloud()
    await fake.start()
    monkeypatch.setattr(api_module, "API_BASE", fake.base)
    yield fake
    await fake.stop()


@pytest.fixture
async def session():
    async with ClientSession() as client_session:
        yield client_session


async def test_properties_parsing(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/property/status"] = {
        "code": 200,
        "data": [
            {"identifier": "heater_temp", "value": "48", "time": 1700000000000},
            {"identifier": "empty", "value": None},
        ],
    }
    client = VattiClient(session, token="tk")
    props = await client.properties("dev-1")
    assert props == {"heater_temp": {"value": "48", "time": 1700000000000}}


async def test_properties_signature_headers(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/property/status"] = {"code": 200, "data": []}
    client = VattiClient(session, token="tk")
    await client.properties("dev-1")
    # 请求体包含固定字段
    _, body = cloud.requests[-1]
    assert body["accessKeyId"]
    assert body["accessToken"] == "tk"
    assert isinstance(body["timestamp"], str)


async def test_command_payload(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/rrpc"] = {
        "code": 200,
        "data": {"rrpcCode": "SUCCESS"},
    }
    client = VattiClient(session, token="tk")
    await client.send_command("dev-1", {"heater_temp": 45})
    _, body = cloud.requests[-1]
    assert json.loads(body["messageContent"]) == {
        "heater_temp": "45",
        "controller": "1",
    }
    assert body["timeout"] == 5000


async def test_command_offline(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/rrpc"] = {
        "code": 200,
        "data": {"rrpcCode": "DEVICE_OFFLINE"},
    }
    client = VattiClient(session, token="tk")
    with pytest.raises(VattiDeviceOfflineError):
        await client.send_command("dev-1", {"powerStat": 1})


async def test_auth_error(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/property/status"] = {
        "code": 401,
        "message": "token expired",
    }
    client = VattiClient(session, token="tk")
    with pytest.raises(VattiAuthError):
        await client.properties("dev-1")


async def test_generic_api_error(cloud, session) -> None:
    cloud.responses["/api/app/v1/device/property/status"] = {
        "code": 500,
        "message": "boom",
    }
    client = VattiClient(session, token="tk")
    with pytest.raises(VattiApiError):
        await client.properties("dev-1")


async def test_send_sms_uses_ticket(cloud, session) -> None:
    cloud.responses["/api/app/v1/user/verification/code"] = {"code": 200, "data": None}
    ticket = CaptchaTicket("cid", "lot", "out", "pass", "t")
    client = VattiClient(session)
    await client.send_sms_code("13800138000", ticket)
    _, body = cloud.requests[-1]
    assert body["phone"] == "13800138000"
    assert body["captchaId"] == "cid"
    assert body["lotNumber"] == "lot"


async def test_energy_overview(cloud, session) -> None:
    cloud.responses["/ecm/getNewWaterGas"] = {
        "code": 200,
        "data": {
            "totalYearGas": json.dumps({"value": 42.5}),
            "dataList": json.dumps([{"time": "2026-11-24", "value": 100}]),
        },
    }
    client = VattiClient(session, token="tk")
    overview = await client.energy_overview("dev-1", is_gas=True)
    assert overview.year == 42.5
    assert overview.buckets[0]["value"] == 100
