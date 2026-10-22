from pathlib import Path

import yaml
from dotenv import dotenv_values

# Project Root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Project Directories
TASKS_DIR = PROJECT_ROOT / "tasks"

# Project Files
MCP_CONFIG = PROJECT_ROOT / "mcp.json"
APPROVAL_CONFIG = PROJECT_ROOT / "approval.yaml"
AGENT_COMPOSE = PROJECT_ROOT / "agent" / "compose.yaml"
LITELLM_CONFIG = PROJECT_ROOT / "litellm" / "config.yaml"

# Constants
AGENT_TAG = dotenv_values(PROJECT_ROOT / ".env")["AGENT_TAG"]
MODELS = tuple(
    m["model_name"] for m in yaml.safe_load(LITELLM_CONFIG.read_text())["model_list"]
)
TIERS = ("requirement", "research_questions", "lit_review")
STAGES = (
    "research_questions",
    "lit_review",
    "research_design",
    "experiments",
    "analysis",
    "report",
)
