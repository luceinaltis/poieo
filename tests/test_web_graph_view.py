"""The board can name authored steps without receiving their instructions."""

from starlette.testclient import TestClient
from test_web_server import stub_daemon, stub_runner

from poieo.web.server import create_app


def test_graph_shape_includes_the_authored_step_description(tmp_path):
    graph = {
        "name": "review",
        "entry": "step_1",
        "nodes": [
            {
                "id": "step_1",
                "type": "agent",
                "description": "Review the draft",
                "prompt": "Instructions stay out of the board listing.",
                "system": "System instructions stay out too.",
            }
        ],
    }
    client = TestClient(create_app(stub_daemon(tmp_path, [stub_runner(graph=graph)])))

    node = client.get("/api/tasks").json()["tasks"][0]["shape"]["nodes"][0]

    assert node["description"] == "Review the draft"
    assert node["id"] == "step_1"
    assert "prompt" not in node
    assert "system" not in node
