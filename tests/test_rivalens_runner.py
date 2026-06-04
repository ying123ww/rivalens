import unittest
from unittest.mock import patch

from backend.server import rivalens_runner


class FakeTraceStore:
    def __init__(self, *, persist_error: Exception | None = None):
        self.enabled = True
        self.persist_error = persist_error
        self.started = []
        self.persisted = []
        self.failed = []

    def start_run(self, **kwargs):
        self.started.append(kwargs)

    def persist_state(self, state, **kwargs):
        if self.persist_error:
            raise self.persist_error
        self.persisted.append((state, kwargs))
        return type(
            "Result",
            (),
            {
                "run_id": kwargs["run_id"],
                "step_count": 0,
                "transition_count": 0,
                "evidence_count": 0,
                "claim_count": 0,
                "claim_evidence_count": 0,
                "artifact_count": 0,
            },
        )()

    def mark_failed_run(self, **kwargs):
        self.failed.append(kwargs)


class RivalensRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_persists_workflow_state_with_trace_ids(self):
        expected_state = {"task": {"run_id": "rid"}}
        store = FakeTraceStore()

        async def fake_run_task(*args, **kwargs):
            self.assertEqual(kwargs["run_id"], "rid")
            self.assertTrue(kwargs["langsmith_trace_id"])
            return expected_state

        with (
            patch.object(
                rivalens_runner,
                "_resolve_run_rivalens_task",
                return_value=fake_run_task,
            ),
            patch.object(rivalens_runner, "trace_store", store),
        ):
            state = await rivalens_runner.run_rivalens_task(
                "Compare Alpha and Beta",
                run_id="rid",
            )

        self.assertIs(state, expected_state)
        self.assertEqual(store.started[0]["run_id"], "rid")
        self.assertEqual(store.persisted[0][1]["run_id"], "rid")

    async def test_runner_returns_state_when_trace_persistence_fails(self):
        expected_state = {"task": {"run_id": "rid"}}
        store = FakeTraceStore(persist_error=RuntimeError("database unavailable"))

        async def fake_run_task(*args, **kwargs):
            return expected_state

        with (
            patch.object(
                rivalens_runner,
                "_resolve_run_rivalens_task",
                return_value=fake_run_task,
            ),
            patch.object(rivalens_runner, "trace_store", store),
        ):
            state = await rivalens_runner.run_rivalens_task(
                "Compare Alpha and Beta",
                run_id="rid",
            )

        self.assertIs(state, expected_state)

    async def test_runner_persists_failed_run_before_reraising(self):
        store = FakeTraceStore()

        async def fake_run_task(*args, **kwargs):
            raise RuntimeError("workflow failed")

        with (
            patch.object(
                rivalens_runner,
                "_resolve_run_rivalens_task",
                return_value=fake_run_task,
            ),
            patch.object(rivalens_runner, "trace_store", store),
        ):
            with self.assertRaisesRegex(RuntimeError, "workflow failed"):
                await rivalens_runner.run_rivalens_task(
                    "Compare Alpha and Beta",
                    run_id="rid",
                )

        self.assertEqual(store.failed[0]["run_id"], "rid")
        self.assertEqual(store.failed[0]["query"], "Compare Alpha and Beta")


if __name__ == "__main__":
    unittest.main()
