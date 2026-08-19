import logging

from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from springbootai.annotations import FileUpload, PostMapping, RequestPart
from springbootai.web.web_context import WebApplicationContext


class _UploadController:
    @PostMapping("/upload")
    async def upload(
        self,
        file: UploadFile = RequestPart(
            "file", allowed_extensions="txt,pdf", max_size=4,
        ),
    ):
        return {"filename": file.filename, "size": file.size}

    @PostMapping("/optional")
    async def optional(self, file: UploadFile | None = FileUpload("asset", required=False)):
        return {"present": file is not None}


def _client_for_controller():
    context = object.__new__(WebApplicationContext)
    context._logger = logging.getLogger("tests.upload")
    context._exception_handlers = {}
    app = FastAPI()
    controller = _UploadController()
    app.add_api_route(
        "/upload",
        context._create_endpoint(controller, controller.upload.__func__, "/upload"),
        methods=["POST"],
    )
    app.add_api_route(
        "/optional",
        context._create_endpoint(controller, controller.optional.__func__, "/optional"),
        methods=["POST"],
    )
    return TestClient(app)


def test_request_part_binds_upload_file_and_validates_extension_and_size():
    client = _client_for_controller()
    response = client.post(
        "/upload", files={"file": ("note.txt", b"abcd", "text/plain")}
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"filename": "note.txt", "size": 4}

    bad_extension = client.post(
        "/upload", files={"file": ("note.exe", b"abcd", "application/octet-stream")}
    )
    assert bad_extension.status_code == 400

    too_large = client.post(
        "/upload", files={"file": ("note.txt", b"abcde", "text/plain")}
    )
    assert too_large.status_code == 400


def test_file_upload_alias_allows_optional_part():
    client = _client_for_controller()
    response = client.post("/optional")
    assert response.status_code == 200
    assert response.json()["data"] == {"present": False}
