#!/bin/bash
# setup_credentials.sh — one-command local credential bootstrap (devnet, $0)
#
# HUMAN: run this once → it handles H2 (keypair + funding) automatically.
# What it does:
#   1. cp .env.example .env (if .env missing)
#   2. solana-keygen new → ./agent_keypair.json (throwaway DEVNET key, if missing)
#   3. solana config set --url devnet
#   4. airdrop 2 SOL x2 with retries (devnet faucet is rate-limited)
#   5. prints pubkey + balance + next human handoffs
#
# SAFETY: this key must NEVER touch mainnet. Mainnet = fresh keys (Phase C).

set -e
cd "$(dirname "$0")/.."

echo "=== Stockulus credential setup (devnet) ==="

# 1. .env
if [ -f .env ]; then
  echo "[1/5] .env exists — leaving it untouched."
else
  cp .env.example .env
  echo "[1/5] Created .env from .env.example (placeholders inside)."
fi

# 2. Agent keypair (source AGENT_KEYPAIR_PATH from .env if set)
set -a; . ./.env; set +a
: "${AGENT_KEYPAIR_PATH:=./agent_keypair.json}"
if [ -f "$AGENT_KEYPAIR_PATH" ]; then
  echo "[2/5] Keypair exists at $AGENT_KEYPAIR_PATH — NOT regenerating."
else
  solana-keygen new --no-bip39-passphrase -s -o "$AGENT_KEYPAIR_PATH" --force
  echo "[2/5] Generated throwaway devnet keypair at $AGENT_KEYPAIR_PATH"
fi
PUBKEY=$(solana-keygen pubkey "$AGENT_KEYPAIR_PATH")
echo "      pubkey: $PUBKEY"

# 3. Point CLI at devnet
: "${RPC_URL:=https://api.devnet.solana.com}"
solana config set --url "$RPC_URL" > /dev/null
echo "[3/5] Solana CLI → $RPC_URL"

# 4. Fund (devnet airdrop, faucet rate-limits — retry, non-fatal)
echo "[4/5] Funding $PUBKEY (devnet airdrop)..."
FUNDED=0
for i in 1 2 3 4 5; do
  if solana airdrop 2 -k "$AGENT_KEYPAIR_PATH" > /dev/null 2>&1; then FUNDED=1; fi
  BAL=$(solana balance -k "$AGENT_KEYPAIR_PATH" 2>/dev/null || echo "unknown")
  echo "      attempt $i → balance: $BAL"
  sleep 10
done

# 5. Handoffs
echo ""
echo "[5/5] Credential status:"
echo "  RPC_URL=$RPC_URL"
echo "  AGENT_KEYPAIR_PATH=$AGENT_KEYPAIR_PATH ($PUBKEY, balance: $BAL)"
echo "  ANCHOR_PROGRAM_ID=$ANCHOR_PROGRAM_ID"
echo "  VAULT_PROGRAM_ID=$VAULT_PROGRAM_ID"
echo ""
if [ "$FUNDED" = "0" ]; then
  echo "  ⚠ Airdrop failed (faucet rate-limit). HUMAN: https://faucet.solana.com → paste $PUBKEY"
fi
echo "  HUMAN HANDOFFS remaining (see .env.example for details):"
echo "    H1 — deploy programs, paste ANCHOR_PROGRAM_ID + VAULT_PROGRAM_ID into .env"
echo "    H3 — paste CLAWPUMP_API_KEY (cpk_…) from https://clawpump.tech/dashboard (bounty #2)"
echo "    H4 — fill DBC_POOL_XAAPL/XTSLA/XNVDA after create_pool (one per symbol)"
echo "    (NANSEN_API_KEY is Phase C — leave the placeholder.)"
echo ""
echo "=== Done. Verify: solana balance -k $AGENT_KEYPAIR_PATH ==="
