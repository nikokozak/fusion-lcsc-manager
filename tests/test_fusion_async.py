"""Small regression check for Fusion's non-blocking preview path."""

import importlib.util
import json
import sys
import types
from pathlib import Path


def _load_addin():
    core = types.ModuleType("adsk.core")

    class Handler:
        def __init__(self):
            pass

    core.CustomEventHandler = Handler
    core.HTMLEventHandler = Handler
    core.CommandEventHandler = Handler
    core.CommandCreatedEventHandler = Handler
    adsk = types.ModuleType("adsk")
    adsk.core = core
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = core

    path = Path(__file__).parent.parent / "fusion" / "LCSCManagerFusion" / "LCSCManagerFusion.py"
    spec = importlib.util.spec_from_file_location("fusion_addin_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_is_dispatched_and_skips_the_slow_detail_lookup(monkeypatch):
    addin = _load_addin()
    started = []

    class Thread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs)

    monkeypatch.setattr(addin.threading, "Thread", Thread)
    args = types.SimpleNamespace(
        action="preview",
        data=json.dumps({"request_id": "1", "lcsc_id": "C2040"}),
        returnData="",
    )
    addin.IncomingHandler().notify(args)
    assert json.loads(args.returnData)["pending"] is True
    assert started[0]["target"] is addin._run_async

    class Response:
        def __init__(self, result=None, content=b""):
            self.result = result or []
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"result": self.result}

    class Client:
        def search_component(self, _lcsc_id):
            raise AssertionError("full detail lookup should not run when a preview exists")

    addin.client = Client()
    image = "https://jlcpcb.com/api/file/downloadByFileSystemAccessId/123"
    monkeypatch.setattr(
        addin.requests,
        "get",
        lambda url, **_kwargs: Response(content=b"\xff\xd8\xffimage")
        if url == image
        else Response(result=[{"docType": 2, "svg": "<svg/>"}]),
    )
    result = json.loads(addin._preview({
        "lcsc_id": "C2040",
        "component": {
            "lcsc_id": "C2040",
            "name": "RP2040",
            "price": 1.25,
            "image": image,
        },
    }))
    assert result["ok"] is True
    assert result["component"]["name"] == "RP2040"
    assert result["component"]["price"][0]["price"] == 1.25
    assert result["component"]["image"] == {
        "mime": "image/jpeg",
        "hex": b"\xff\xd8\xffimage".hex(),
    }


def test_jlcpcb_search_builds_the_product_image_url(monkeypatch):
    addin = _load_addin()
    client = addin.LCSCAPIClient(config={"api_cache_enabled": False})
    monkeypatch.setattr(client, "_make_request", lambda **_kwargs: {
        "code": 200,
        "data": {"componentPageInfo": {"list": [{
            "componentCode": "C2040",
            "componentModelEn": "RP2040",
            "minImageAccessId": "8583419804341948416",
            "productBigImageAccessId": "8583419803382398976",
        }]}},
    })

    result = client.search_jlcpcb("RP2040")[0]

    assert result["lcsc"]["number"] == "C2040"
    assert result["image"] == (
        "https://jlcpcb.com/api/file/downloadByFileSystemAccessId/"
        "8583419803382398976"
    )
