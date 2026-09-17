#!/bin/bash
# demo.sh — Run Stockulus devnet demo (loads .env, runs agent for 3 cycles)

set -e

echo "=== Stockulus Devnet Demo ==="

# Load .env if present
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
else
  echo "No .env found — copy .env.example to .env and fill in values."
  exit 1
fi

if [ -z "$ANCHOR_PROGRAM_ID" ] || [ -z "$AGENT_KEYPAIR_PATH" ]; then
  echo "Missing env vars (ANCHOR_PROGRAM_ID, AGENT_KEYPAIR_PATH). Run scripts/setup_credentials.sh first."
  exit 1
fi

# Reject unfilled placeholders (fail loud, not silent)
if [ "$ANCHOR_PROGRAM_ID" = "11111111111111111111111111111111" ]; then
  echo "ANCHOR_PROGRAM_ID is still the placeholder. HUMAN HANDOFF H1:"
  echo "  deploy first (scripts/deploy_devnet.sh or CI tag), then paste the real program ID into .env"
  exit 1
fi
if [ ! -f "$AGENT_KEYPAIR_PATH" ]; then
  echo "Keypair not found at $AGENT_KEYPAIR_PATH. Run scripts/setup_credentials.sh first."
  exit 1
fi

# Degraded-mode warnings (non-fatal — rest of demo still runs)
case "$CLAWPUMP_API_KEY" in
  ""|"cpk_xxx"*) echo "⚠ CLAWPUMP_API_KEY placeholder → agent-launch + earnings demo skipped (H3)." ;;
esac
case "$NANSEN_API_KEY" in
  ""|"nansen_xxx"*) echo "ℹ NANSEN_API_KEY placeholder → onchain_flow_signal stays neutral (Phase C)." ;;
esac

echo "Starting agent for 3 trading cycles..."
cd app/agent
python -m app.agent
echo "=== Demo Complete ==="