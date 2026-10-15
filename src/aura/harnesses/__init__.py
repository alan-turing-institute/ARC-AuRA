from aura.harnesses.ai_scientist_v2 import ai_scientist_v2_command
from aura.harnesses.claude_code import claude_code_command
from aura.harnesses.opencode import opencode_command

HARNESSES = {
    "claude-code": claude_code_command,
    "opencode": opencode_command,
    "ai-scientist-v2": ai_scientist_v2_command,
}
