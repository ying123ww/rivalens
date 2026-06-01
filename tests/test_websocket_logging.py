import json
import unittest
from pathlib import Path
from uuid import uuid4

from backend.server.server_utils import CustomLogsHandler


class ClosedWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class RecordingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, data):
        self.messages.append(data)


class CustomLogsHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_json_records_disconnect_when_websocket_is_closed(self):
        handler = CustomLogsHandler(ClosedWebSocket(), f"disconnect probe {uuid4()}")
        try:
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
            try:
                Path(handler.log_file).unlink(missing_ok=True)
            except PermissionError:
                pass

        events = log_data["events"]
        self.assertEqual(events[0]["data"]["content"], "research_step_finalized")
        self.assertEqual(events[1]["data"]["content"], "websocket_disconnected")
        self.assertEqual(
            log_data["content"]["report"],
            "Report chunk after disconnect.",
        )

    async def test_log_messages_are_batched_for_websocket_but_written_fully(self):
        websocket = RecordingWebSocket()
        handler = CustomLogsHandler(websocket, f"batch probe {uuid4()}")
        try:
            for index in range(19):
                await handler.send_json({
                    "type": "logs",
                    "content": "collector",
                    "output": f"log {index}",
                })
            self.assertEqual(websocket.messages, [])

            await handler.send_json({
                "type": "logs",
                "content": "collector",
                "output": "log 19",
            })

            with open(handler.log_file, encoding="utf-8") as file:
                log_data = json.load(file)
        finally:
            try:
                Path(handler.log_file).unlink(missing_ok=True)
            except PermissionError:
                pass

        self.assertEqual(len(log_data["events"]), 20)
        self.assertEqual(len(websocket.messages), 1)
        self.assertEqual(websocket.messages[0]["content"], "log_batch")
        self.assertEqual(websocket.messages[0]["metadata"]["count"], 20)


if __name__ == "__main__":
    unittest.main()
