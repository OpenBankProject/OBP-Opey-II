#!/bin/bash
set -e

echo "Removing existing virtualenv..."
poetry env remove --all

echo "Reinstalling dependencies..."
poetry install

echo "Verifying langgraph.prebuilt..."
poetry run python -c "from langgraph.prebuilt import tools_condition, ToolNode; print('OK')"
