import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

backend_path = Path(__file__).resolve().parents[1] / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from backend.server.persistence import get_persistence_config
from backend.server.rivalens_runner import run_rivalens_task


class RivalensPersistenceToggleTest(unittest.IsolatedAsyncioTestCase):
    def test_persistence_config_can_disable_persistence(self):
        with patch.dict(os.environ, {"RIVALENS_PERSISTENCE_ENABLED": "false"}):
            self.assertFalse(get_persistence_config().enabled)

    async def test_runner_skips_persistence_when_disabled(self):
        async def fake_run_task(*args, **kwargs):
            return {"task": {"run_id": "rid_disabled"}}

        with (
            patch.dict(os.environ, {"RIVALENS_PERSISTENCE_ENABLED": "false"}),
            patch(
                "backend.server.rivalens_runner._resolve_run_rivalens_task",
                return_value=fake_run_task,
            ),
            patch("backend.server.rivalens_runner.logger.info") as info_logger,
        ):
            state = await run_rivalens_task("Compare Alpha and Beta")

        self.assertEqual(state["task"]["run_id"], "rid_disabled")
        self.assertTrue(
            any(
                "persistence is disabled" in str(call.args[0])
                for call in info_logger.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
