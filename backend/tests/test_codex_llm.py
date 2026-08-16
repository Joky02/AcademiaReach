from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.search_agent import search_professors
from backend.core.codex_llm import CodexChatModel, codex_invoke_options


class CodexChatModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_ainvoke_uses_named_harness_and_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        model = CodexChatModel(model_name="test-model", timeout_seconds=90)

        with patch(
            "backend.core.codex_llm.run_codex_text",
            new=AsyncMock(return_value='{"answer":"ok"}'),
        ) as run_codex:
            response = await model.ainvoke(
                [
                    SystemMessage(content="Return JSON."),
                    HumanMessage(content="Answer ok."),
                ],
                **codex_invoke_options(model, "compose", schema),
            )

        self.assertEqual(response.content, '{"answer":"ok"}')
        kwargs = run_codex.await_args.kwargs
        self.assertEqual(kwargs["harness"], "compose")
        self.assertEqual(kwargs["model"], "test-model")
        self.assertEqual(kwargs["timeout_seconds"], 90)
        self.assertEqual(kwargs["output_schema"], schema)
        self.assertIn("## SYSTEM INSTRUCTIONS", run_codex.await_args.args[0])
        self.assertIn("## USER", run_codex.await_args.args[0])

    async def test_global_codex_owns_search_backend(self) -> None:
        async def codex_search(**_kwargs):
            yield {"type": "done", "message": "ok"}

        with (
            patch(
                "backend.agents.search_agent.load_yaml_config",
                return_value={
                    "llm": {"provider": "codex"},
                    "search": {},
                },
            ),
            patch(
                "backend.agents.search_agent._search_professors_codex",
                new=codex_search,
            ),
        ):
            messages = [message async for message in search_professors()]

        self.assertEqual(messages, [{"type": "done", "message": "ok"}])


if __name__ == "__main__":
    unittest.main()
