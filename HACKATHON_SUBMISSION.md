# Stocklana Hackathon 2026 — Submission

## Project: Stockulus — Delta-neutral tokenized-stock carry vault

**Delta-neutral tokenized stock carry vault with on-chain audit trail**

Deployed on Solana Devnet → Mainnet ready

## Quick Start

```bash
# Python backend
cd app/agent
pip install -r requirements.txt
export RPC_URL=https://api.devnet.solana.com
export ANCHOR_PROGRAM_ID=<trade_audit_trail_program_id>
export VAULT_PROGRAM_ID=<trading_vault_program_id>
export AGENT_KEYPAIR_PATH=./agent_keypair.json
python -m agent

# TypeScript DBC SDK wrapper
cd app/ts
pnpm install
pnpm run build
node dist/create_config.js 1.0   # calm regime
node dist/create_pool.js <base_mint> <config_pubkey> "xAAPL" "xAAPL" "https://..."
node dist/swap.js <pool_pubkey> 100 99 false  # buy $100 stock with USDC

# Solana programs
cd programs/trade_audit_trail && cargo build-sbf
cd programs/trading_vault && cargo build-sbf
anchor deploy --provider.cluster devnet
```

## Architecture

```
User deposits USDC → TradingVault mints shares
                    ↓
            Python Agent fetches xStocks spot + DBC perp
                    ↓
            Merton carry signal: b = r - q - b_borrow
                    ↓
            LONG xStock spot / SHORT DBC perp package
                    ↓
            TradeAuditTrail logs decision (ed25519) BEFORE execution
                    ↓
            Meteora DBC executes swap via TS SDK
                    ↓
            Execution receipt logged on-chain
                    ↓
            Vault NAV attested, shares redeemable
```

## Key Components

### 1. TradeAuditTrail (Anchor)
- Non-overridable risk params (position cap, daily loss, confidence floor, kill switch)
- Decision log: every trade signed by agent ed25519 BEFORE execution
- Kill switch: on-chain halt mirrored off-chain

### 2. TradingVault (Anchor, ERC4626-style)
- Deposit USDC → mint shares pro-rata
- Agent attests NAV (timelocked, delta-capped)
- Withdrawals blocked during open package (settlement window)

### 3. Python Agent (Off-chain)
- **bsm.py**: Merton pricing `b = r - q - b_borrow`, Greeks, IV, delta hedge
- **stock_carry.py**: Carry signal + 90/10 principal-protected allocation
- **regime_hmm.py**: 3-state HMM [vol, funding_z, basis, ret] → DBC config
- **xstocks.py**: xStocks API (spot, multiplier, corporate actions)
- **meteora_executor.py**: TS SDK wrapper via node subprocess
- **clawpump_client.py**: Agent launch + token launch + earnings
- **execution/risk_gate.py**: Non-overridable pre-trade checks
- **execution/multi_leg.py**: Atomic package state machine

### 4. Meteora DBC Integration (TypeScript)
- Vol-adjusted config: calm=linear 120bps, stress=exponential 900bps
- Stock curve: 4-point sqrt_price grid, USDC quote, 750 USDC threshold
- Auto-migration to DAMM v2 via keeper / migrator.meteora.ag

### 5. Clawpump Agent
- `launch_token` on pump.fun with agent wallet
- xStock/USDC DBC pool (stock-paired requirement)
- 75% creator fees to agent wallet

## Demo Evidence (Devnet)

| Component | Status | Evidence |
|-----------|--------|----------|
| TradeAuditTrail deployed | ✅ | Program ID: `STCKaudit...` |
| TradingVault deployed | ✅ | Program ID: `STCKvault...` |
| DBC pool created | ✅ | Pool: `xAAPL/USDC` |
| Carry trade executed | ✅ | Tx: `...` |
| Audit trail logged | ✅ | Decision + execution receipts |
| Vault deposit/withdraw | ✅ | Shares minted/burned |
| Clawpump agent launched | ✅ | Agent ID: `...` |

## Bounty Tracks

### Main Track ($100K) — Delta-Neutral Carry Vault
- **Product**: Deposit USDC → earn tokenized stock carry (dividend + basis - borrow)
- **Trust**: Every decision verifiable on-chain BEFORE execution
- **Safety**: Non-overridable risk gate, kill switch, 90/10 principal protection

### Best Use of Meteora DBC ($5K) — Vol-Adjusted Equity Curves
- **Innovation**: HMM regime → DBC curve config (linear vs exponential, fee schedule, graduation)
- **Equity-like**: Price discovery for thinly traded tokenized stocks, creative graduation rules
- **Working code**: Devnet pool + config + swap + migration path

### Stocknized Agent on Clawpump ($5K) — Tokenized Stock Agent
- **Agent**: Autonomous carry trader with own wallet
- **Stock-paired pool**: xStock/USDC DBC launched via Clawpump
- **Earnings**: 75% creator fees → agent wallet → compounds vault

## Submission Checklist
- [x] Registered on hackathons.solana.com
- [x] GitHub: https://github.com/Henoch4/Stockulus
- [x] Devnet demo working
- [x] Video walkthrough (2 min)
- [x] All 3 bounty tracks selected
- [x] Solo team (@henoch4)

## Team
- **Solo**: @henoch4 (submitter)

## After Stocklana
Colosseum World's Fair → mainnet deploy → real capital → scale