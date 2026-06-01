import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import WebSocketDisconnect

from backend.server.server_utils import CustomLogsHandler, handle_websocket_communication


class ClosedWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class SlowClosedWebSocket:
    def __init__(self):
        self.send_attempts = 0

    async def send_json(self, data):
        import asyncio

        self.send_attempts += 1
        await asyncio.sleep(0.01)
        raise WebSocketDisconnect()


class DisconnectingWebSocket:
    def __init__(self):
        self._messages = iter(["start {}"])
        self.closed = False

    async def receive_text(self):
        import asyncio

        try:
            return next(self._messages)
        except StopIteration:
            await asyncio.sleep(0)
            raise WebSocketDisconnect()

    async def send_json(self, data):
        return None

    async def send_text(self, data):
        return None

    async def close(self):
        self.closed = True


class StubWebSocketManager:
    def __init__(self):
        self.disconnected = False

    async def disconnect(self, websocket):
        self.disconnected = True
        await websocket.close()


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

    async def test_concurrent_send_json_records_disconnect_once(self):
        import asyncio

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                websocket = SlowClosedWebSocket()
                handler = CustomLogsHandler(websocket, "concurrent disconnect probe")

                await asyncio.gather(
                    *[
                        handler.send_json({
                            "type": "logs",
                            "content": f"event_{index}",
                            "output": f"Event {index}",
                        })
                        for index in range(10)
                    ]
                )

                with open(handler.log_file, encoding="utf-8") as file:
                    log_data = json.load(file)
            finally:
                os.chdir(original_cwd)

        disconnect_events = [
            event
            for event in log_data["events"]
            if event["data"].get("content") == "websocket_disconnected"
        ]
        self.assertEqual(websocket.send_attempts, 1)
        self.assertEqual(len(disconnect_events), 1)

    async def test_websocket_disconnect_cancels_running_task(self):
        import asyncio

        started = asyncio.Event()
        cancelled_event = asyncio.Event()
        cancelled = False

        async def fake_handle_start_command(websocket, data, manager, on_log_handler=None):
            nonlocal cancelled
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled = True
                cancelled_event.set()
                raise

        websocket = DisconnectingWebSocket()
        manager = StubWebSocketManager()

        with patch(
            "backend.server.server_utils.handle_start_command",
            fake_handle_start_command,
        ):
            await handle_websocket_communication(websocket, manager)

        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(cancelled_event.wait(), timeout=1)

        self.assertTrue(cancelled)
        self.assertTrue(manager.disconnected)
        self.assertTrue(websocket.closed)


if __name__ == "__main__":
    unittest.main()
