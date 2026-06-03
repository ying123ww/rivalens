import json
import os
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi import WebSocketDisconnect

from backend.server.server_utils import (
    CustomLogsHandler,
    _is_websocket_disconnect_error,
    handle_start_command,
    handle_websocket_communication,
)


class ClosedWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class RecordingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, data):
        self.messages.append(data)


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


class StoppingWebSocket:
    def __init__(self):
        self._messages = iter(["start {}", "stop"])
        self.closed = False
        self.sent = []

    async def receive_text(self):
        import asyncio

        try:
            message = next(self._messages)
            if message == "stop":
                await asyncio.sleep(0)
            return message
        except StopIteration:
            raise WebSocketDisconnect()

    async def send_json(self, data):
        self.sent.append(data)

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


class StubReportStore:
    def __init__(self):
        self.records = {}

    async def get_report(self, research_id):
        return self.records.get(research_id)

    async def upsert_report(self, research_id, record):
        self.records[research_id] = record


class FailingReportStore:
    async def get_report(self, research_id):
        return None

    async def upsert_report(self, research_id, record):
        raise OSError("reports.json is locked")


class StreamingManager:
    async def start_streaming(self, *args, **kwargs):
        return {
            "run_id": "rid_stream",
            "report": "Structured streamed report",
            "report_artifacts": {"markdown": "outputs/rivalens/competitor_analysis.md"},
            "trace_summary": {"claim_count": 1},
            "assessments": {"claim_support_reviews": [{"id": "csr_1"}]},
            "evidence_index": [{"id": "ev_1"}],
            "analysis_claims": [{"id": "claim_1", "evidence_ids": ["ev_1"]}],
            "competitor_knowledge": [{"id": "knowledge_1"}],
            "state": {"task": {"run_id": "rid_stream"}},
        }


class InspectingStreamingManager:
    def __init__(self, store):
        self.store = store
        self.running_snapshot = None

    async def start_streaming(self, *args, **kwargs):
        self.running_snapshot = self.store.records.get("rid_running")
        return "Done"


class CustomLogsHandlerTest(unittest.IsolatedAsyncioTestCase):
    def test_starlette_not_connected_runtime_is_disconnect(self):
        self.assertTrue(
            _is_websocket_disconnect_error(
                RuntimeError('WebSocket is not connected. Need to call "accept" first.')
            )
        )

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
        with patch.dict(os.environ, {"RIVALENS_WS_LOG_BATCH_SIZE": "20"}):
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

    async def test_concurrent_send_json_records_disconnect_once(self):
        import asyncio

        websocket = SlowClosedWebSocket()
        with patch.dict(os.environ, {"RIVALENS_WS_LOG_BATCH_SIZE": "1"}):
            handler = CustomLogsHandler(websocket, f"concurrent disconnect probe {uuid4()}")
        try:
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
            try:
                Path(handler.log_file).unlink(missing_ok=True)
            except PermissionError:
                pass

        disconnect_events = [
            event
            for event in log_data["events"]
            if event["data"].get("content") == "websocket_disconnected"
        ]
        self.assertEqual(websocket.send_attempts, 1)
        self.assertEqual(len(disconnect_events), 1)

    async def test_websocket_disconnect_keeps_running_task_alive(self):
        import asyncio

        started = asyncio.Event()
        allow_complete = asyncio.Event()
        completed = asyncio.Event()
        cancelled = False

        async def fake_handle_start_command(
            websocket,
            data,
            manager,
            on_log_handler=None,
            report_store=None,
        ):
            nonlocal cancelled
            started.set()
            try:
                await allow_complete.wait()
                completed.set()
            except asyncio.CancelledError:
                cancelled = True
                raise

        websocket = DisconnectingWebSocket()
        manager = StubWebSocketManager()

        with patch(
            "backend.server.server_utils.handle_start_command",
            fake_handle_start_command,
        ):
            await handle_websocket_communication(websocket, manager)

        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertFalse(cancelled)

        allow_complete.set()
        await asyncio.wait_for(completed.wait(), timeout=1)

        self.assertTrue(manager.disconnected)
        self.assertTrue(websocket.closed)

    async def test_stop_command_cancels_running_task(self):
        import asyncio

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_handle_start_command(
            websocket,
            data,
            manager,
            on_log_handler=None,
            report_store=None,
        ):
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        websocket = StoppingWebSocket()
        manager = StubWebSocketManager()

        with patch(
            "backend.server.server_utils.handle_start_command",
            fake_handle_start_command,
        ):
            await handle_websocket_communication(websocket, manager)

        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(cancelled.wait(), timeout=1)

        self.assertTrue(
            any(message.get("content") == "run_cancelled" for message in websocket.sent)
        )
        self.assertTrue(manager.disconnected)
        self.assertTrue(websocket.closed)

    async def test_streaming_rivalens_report_store_keeps_structured_state(self):
        websocket = RecordingWebSocket()
        store = StubReportStore()
        data = json.dumps({
            "research_id": "rid_stream",
            "task": "Compare Alpha and Beta",
            "report_type": "rivalens",
            "report_source": "web",
            "tone": "Objective",
        })

        async def fake_generate_report_files(report, filename, **kwargs):
            return {
                "markdown": f"outputs/{filename}.md",
                "html": f"outputs/{filename}.html",
                "pdf": f"outputs/{filename}.pdf",
                "docx": f"outputs/{filename}.docx",
            }

        with patch(
            "backend.server.server_utils.generate_report_files",
            fake_generate_report_files,
        ):
            await handle_start_command(
                websocket,
                f"start {data}",
                StreamingManager(),
                report_store=store,
            )

        record = store.records["rid_stream"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["answer"], "Structured streamed report")
        self.assertEqual(record["state"]["task"]["run_id"], "rid_stream")
        self.assertEqual(record["analysis_claims"][0]["id"], "claim_1")
        self.assertEqual(record["evidence_index"][0]["id"], "ev_1")
        self.assertEqual(record["assessments"]["claim_support_reviews"][0]["id"], "csr_1")
        self.assertEqual(record["report_artifacts"]["markdown"], "outputs/rid_stream.md")
        self.assertNotIn("rivalens_response", record["artifacts"])

    async def test_streaming_run_persists_running_progress(self):
        websocket = RecordingWebSocket()
        store = StubReportStore()
        manager = InspectingStreamingManager(store)
        data = json.dumps({
            "research_id": "rid_running",
            "task": "Compare Alpha and Beta",
            "report_type": "research_report",
            "report_source": "web",
            "tone": "Objective",
        })

        async def fake_generate_report_files(report, filename, **kwargs):
            return {"markdown": f"outputs/{filename}.md"}

        with patch(
            "backend.server.server_utils.generate_report_files",
            fake_generate_report_files,
        ):
            await handle_start_command(
                websocket,
                f"start {data}",
                manager,
                report_store=store,
            )

        running_record = manager.running_snapshot
        self.assertEqual(running_record["status"], "running")
        self.assertEqual(running_record["orderedData"][0]["type"], "question")
        self.assertTrue(
            any(item.get("content") == "log_batch" for item in running_record["orderedData"])
        )

    async def test_report_store_write_failure_does_not_stop_streaming_run(self):
        websocket = RecordingWebSocket()
        data = json.dumps({
            "research_id": "rid_locked_store",
            "task": "Compare Alpha and Beta",
            "report_type": "research_report",
            "report_source": "web",
            "tone": "Objective",
        })

        async def fake_generate_report_files(report, filename, **kwargs):
            return {"markdown": f"outputs/{filename}.md"}

        with patch(
            "backend.server.server_utils.generate_report_files",
            fake_generate_report_files,
        ):
            await handle_start_command(
                websocket,
                f"start {data}",
                StreamingManager(),
                report_store=FailingReportStore(),
            )

        self.assertTrue(
            any(message.get("type") == "path" for message in websocket.messages)
        )


if __name__ == "__main__":
    unittest.main()
