from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.search_agent import search_professors
from backend.core.agent_llm import agent_invoke_options, is_harness_llm
from backend.core.llm import resolve_agent_backend, resolve_model_provider
from backend.core.pi_llm import PiChatModel


class PiChatModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_ainvoke_routes_selected_api_through_named_harness(self) -> None:
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        model = PiChatModel(
            provider_name="deepseek",
            model_name="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key="secret-test-key",
            timeout_seconds=90,
        )

        with patch(
            "backend.core.pi_llm.run_pi_text",
            new=AsyncMock(return_value='{"answer":"ok"}'),
        ) as run_pi:
            response = await model.ainvoke(
                [
                    SystemMessage(content="Return JSON."),
                    HumanMessage(content="Answer ok."),
                ],
                **agent_invoke_options(model, "compose", schema),
            )

        self.assertEqual(response.content, '{"answer":"ok"}')
        kwargs = run_pi.await_args.kwargs
        self.assertEqual(kwargs["harness"], "compose")
        self.assertEqual(kwargs["timeout_seconds"], 90)
        self.assertEqual(kwargs["output_schema"], schema)
        self.assertEqual(kwargs["model_config"]["provider"], "deepseek")
        self.assertEqual(kwargs["model_config"]["api_key"], "secret-test-key")
        self.assertNotIn("api_key", model._identifying_params)
        self.assertTrue(is_harness_llm(model))

    async def test_global_pi_owns_search_backend(self) -> None:
        async def pi_search(**kwargs):
            self.assertEqual(kwargs["agent_backend"], "pi")
            yield {"type": "done", "message": "ok"}

        with (
            patch(
                "backend.agents.search_agent.load_yaml_config",
                return_value={
                    "llm": {
                        "agent_backend": "pi",
                        "provider": "deepseek",
                    },
                    "search": {},
                },
            ),
            patch(
                "backend.agents.search_agent._search_professors_codex",
                new=pi_search,
            ),
        ):
            messages = [message async for message in search_professors()]

        self.assertEqual(messages, [{"type": "done", "message": "ok"}])

    def test_new_and_legacy_backend_config_resolution(self) -> None:
        self.assertEqual(resolve_agent_backend({"provider": "codex"}), "codex")
        self.assertEqual(
            resolve_agent_backend({"agent_backend": "pi", "provider": "openai"}),
            "pi",
        )
        self.assertEqual(resolve_model_provider({"provider": "codex"}), "openai")
        self.assertEqual(resolve_model_provider({"provider": "deepseek"}), "deepseek")


if __name__ == "__main__":
    unittest.main()
