from pathlib import Path

from dotenv import dotenv_values

# Project Root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Project Directories
TASKS_DIR = PROJECT_ROOT / "tasks"

# Constants
AGENT_TAG = dotenv_values(PROJECT_ROOT / ".env")["AGENT_TAG"]
TIERS = ("ideation", "research_questions", "lit_review")
