import io
import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/python"))
from paa_core.protocol import MAX_LINE_BYTES, handle, serve, CoreService


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = CoreService(Path(self.temp.name))

    def tearDown(self):
        self.service.summary.shutdown()
        self.service.transcription.shutdown()
        self.temp.cleanup()

    def test_health_is_actual_runtime_and_unavailable_features(self):
        response, stopping = handle({"id": "健康", "method": "health"})
        self.assertEqual(response["id"], "健康")
        self.assertTrue(response["result"]["pythonVersion"].startswith("3.12."))
        self.assertTrue(response["result"]["processId"] > 0)
        self.assertEqual(len(response["result"]["capabilities"]), 3)
        self.assertTrue(all(not item["available"] for item in response["result"]["capabilities"]))
        self.assertFalse(stopping)

    def test_meetings_are_empty_without_creating_data(self):
        response, _ = handle({"id": "2", "method": "meetings.list"}, self.service)
        self.assertEqual(response, {"id": "2", "result": {"meetings": [], "hasMore": False}})

    def test_rejects_invalid_structures(self):
        for request in [None, [], "health", {}, {"id": 1}, {"id": ""},
                        {"id": "a", "method": 4}, {"id": "a", "method": "health", "extra": 1}]:
            with self.subTest(request=request):
                response, stopping = handle(request)
                self.assertEqual(response["error"]["code"], "invalid_request")
                self.assertNotIn("result", response)
                self.assertFalse(stopping)

    def test_unknown_method_and_parameters_have_errors(self):
        for request, code in [
            ({"id": "1", "method": "unknown"}, "method_not_found"),
            ({"id": "1", "method": "health", "params": {"key": "value"}}, "invalid_params"),
            ({"id": "1", "method": "health", "params": []}, "invalid_params"),
        ]:
            response, _ = handle(request)
            self.assertEqual(response["id"], "1")
            self.assertEqual(response["error"]["code"], code)

    def test_stream_recovers_after_invalid_json_and_utf8(self):
        source = io.BytesIO(b"bad\n\xff\n" + b'{"id":"ok","method":"meetings.list"}\n')
        target = io.BytesIO()
        serve(source, target, self.service)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual([item.get("error", {}).get("code") for item in responses],
                         ["invalid_json", "invalid_json", None])
        self.assertEqual(responses[-1]["id"], "ok")

    def test_oversized_line_is_drained_and_next_request_survives(self):
        source = io.BytesIO(b"x" * (MAX_LINE_BYTES * 2) + b'\n{"id":"ok","method":"health"}\n')
        target = io.BytesIO()
        serve(source, target, self.service)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], "invalid_request")
        self.assertEqual(responses[1]["id"], "ok")

    def test_shutdown_stops_before_next_request(self):
        source = io.BytesIO(b'{"id":"1","method":"shutdown"}\n{"id":"2","method":"health"}\n')
        target = io.BytesIO()
        serve(source, target, self.service)
        self.assertEqual(json.loads(target.getvalue()), {"id": "1", "result": {"stopping": True}})


if __name__ == "__main__":
    unittest.main()
