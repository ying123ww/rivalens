import unittest

from rivalens.research.actions.utils import stream_output


class ClosedWebSocket:
    async def send_json(self, data):
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


class StreamOutputTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_output_ignores_closed_websocket(self):
        await stream_output(
            "logs",
            "subquery_error",
            "background task log",
            ClosedWebSocket(),
        )


if __name__ == "__main__":
    unittest.main()
