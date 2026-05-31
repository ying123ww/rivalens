import json
import os
import tempfile
import unittest

from backend.server.server_utils import CustomLogsHandler


class ClosedWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class CustomLogsHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_json_records_disconnect_when_websocket_is_closed(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                handler = CustomLogsHandler(ClosedWebSocket(), "disconnect probe")

                await handler.send_json({
                    "type": "logs",
                    "content": "research_step_finalized",
                    "output": "Finalized research step.",
                })
                await handler.send_json({
                    "type": "report",
                    "output": "Report chunk after disconnect.",
                })

                with open(handler.log_file, encoding="utf-8") as file:
                    log_data = json.load(file)
            finally:
                os.chdir(original_cwd)

        events = log_data["events"]
        self.assertEqual(events[0]["data"]["content"], "research_step_finalized")
        self.assertEqual(events[1]["data"]["content"], "websocket_disconnected")
        self.assertEqual(
            log_data["content"]["report"],
            "Report chunk after disconnect.",
        )


if __name__ == "__main__":
    unittest.main()
