#!/bin/bash
# deploy_devnet.sh — Deploy Stockulus to devnet

set -e

echo "=== Stockulus Devnet Deploy ==="

# 0. Credential preflight (fail loud before spending time building)
if [ ! -f .env ]; then
  echo "No .env — run scripts/setup_credentials.sh first (generates keypair + funds it)."
  exit 1
fi
set -a; . ./.env; set +a
if [ ! -f "${AGENT_KEYPAIR_PATH:-./agent_keypair.json}" ]; then
  echo "Keypair missing at ${AGENT_KEYPAIR_PATH:-./agent_keypair.json} — run scripts/setup_credentials.sh first."
  exit 1
fi
echo "Preflight OK: .env + keypair present."

# 1. Build TypeScript
echo "Building TypeScript DBC SDK wrapper..."
cd app/ts
pnpm install
pnpm run build
cd ../..

# 2. Build Anchor programs
echo "Building Anchor programs..."
cd programs/trade_audit_trail
cargo build-sbf
cd ../trading_vault
cargo build-sbf
cd ../..

# 3. Deploy to devnet
echo "Deploying to devnet..."
anchor deploy --provider.cluster devnet

echo "=== Deploy Complete ==="
echo "HUMAN HANDOFF H1 — paste these into .env:"
echo "  export ANCHOR_PROGRAM_ID=<trade_audit_trail_program_id>"
echo "  export VAULT_PROGRAM_ID=<trading_vault_program_id>"
echo "Then: anchor keys sync (updates declare_id! + Anchor.toml), rebuild, redeploy once."