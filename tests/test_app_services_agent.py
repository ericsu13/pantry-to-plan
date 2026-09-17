"""UI-service routing tests for Agent + MCP mode and safe fallback."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import app_services
from schemas import PantryItem, PantryState, PlanningRequest
from tests.fakes import FakeRetriever


ROOT = Path(__file__).resolve().parents[1]


class FailingAgent:
    async def plan(self, pantry, request):
        raise RuntimeError("simulated agent outage")


class AgentRoutingTests(unittest.TestCase):
    def test_mcp_failure_falls_back_to_standard_planner(self):
        fx = json.loads((ROOT / "fixtures/01_well_stocked_veg_italian.json").read_text())
        pantry = PantryState(
            items=[
                PantryItem(
                    ingredient_id=key,
                    display_name=key.replace("_", " "),
                    quantity_g=value,
                    confidence=1.0,
                )
                for key, value in fx["pantry"]["items"].items()
            ]
        )
        request = PlanningRequest.model_validate(fx["request"])
        with patch.object(app_services, "get_retriever", return_value=FakeRetriever()):
            result = app_services.run_plan(
                pantry,
                request,
                mode="mcp_agent",
                mcp_agent=FailingAgent(),
            )
        self.assertEqual(len(result.day_plans), request.days)
        self.assertIn("MCP_AGENT_FALLBACK", result.warnings)
        self.assertEqual(result.trace[0].step, "agent_fallback")


if __name__ == "__main__":
    unittest.main()
