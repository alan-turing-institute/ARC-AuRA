FROM python:3.12-slim

# System tools and Node 22 (needed by Claude Code and OpenCode)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl git ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# Harnesses
RUN npm install -g @anthropic-ai/claude-code@2.1.282 opencode-ai@1.18.32

# Scientific Python stack
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Run as an ordinary user, never root
RUN useradd --create-home --uid 1000 agent
USER agent
WORKDIR /workspace
