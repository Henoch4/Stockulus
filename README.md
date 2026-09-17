# Stockulus — Tokenized Stock Carry Vault

**Stocklana Hackathon Submission — Solana Foundation**

## Project Overview

Stockulus is a delta-neutral carry vault for tokenized equities on Solana. The core thesis: tokenized stocks (xAAPL, xTSLA, xNVDA via xStocks/Backpack) trade 24/7 with a persistent basis vs spot + dividend yield — a structural carry opportunity.

### Tracks Entered
- **Main Track ($100K)**: Delta-neutral tokenized stock carry vault with on-chain audit trail
- **Best Use of Meteora DBC ($5K)**: Volatility-adjusted DBC configs for equity-like assets
- **Stocknized Agent on Clawpump ($5K)**: Agent launch + stock-paired DBC pool

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           Stockulus                               │
├─────────────────────────────────────────────────────────────────┤
│  Python Agent (Off-chain)                                       │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────┐ ┌───────────┐  │
│  │ xStocks API │ │ Merton Carry │ │ HMM Regime │ │ Multi-Leg │  │
│  │   Adapter   │ │   Signal     │ │  Detector  │ │ Execution │  │
│  └──────┬──────┘ └──────┬───────┘ └─────┬──────┘ └─────┬─────┘  │
│         │               │               │               │        │
│         └───────────────┼───────────────┼───────────────┘        │
│                         ▼               ▼                        │
│              ┌────────────────────────┐                          │
│              │     Risk Gate          │                          │
│              │ (Non-overridable)      │                          │
│              └───────────┬────────────┘                          │
│                         │                                        │
│                         ▼                                        │
│              ┌────────────────────────┐                          │
│              │  Solana Audit Logger   │                          │
│              │  (TradeAuditTrail)     │                          │
│              └───────────┬────────────┘                          │
│                         │                                        │
│                         ▼                                        │
│              ┌────────────────────────┐                          │
│              │  Meteora DBC Executor  │                          │
│              │  (TS SDK via node)     │                          │
│              └────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    On-Chain (Anchor)                            │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐  │
│  │ TradeAuditTrail     │  │ TradingVault (ERC4626-style)    │  │
│  │ - Risk params       │  │ - Deposit/Withdraw              │  │
│  │ - Decision log      │  │ - NAV attestation               │  │
│  │ - Kill switch       │  │ - Package open guard            │  │
│  └─────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. Delta-Neutral Carry Engine
- **Merton cost-of-carry**: `b = r - q - b_borrow` (r=risk-free, q=div yield, b_borrow=borrow fee)
- **Signal**: LONG spot (xStock) + SHORT DBC perp when carry >50bps & basis >5bps
- **Confidence**: `min(0.7 + basis_bps/200 + carry_ann/200, 0.9)`

### 2. On-Chain Audit Trail (TradeAuditTrail)
- Every decision signed by agent ed25519 key → logged BEFORE execution
- Non-overridable risk params (position caps, daily loss, confidence floor, kill switch)
- Decision + execution receipts immutable on-chain

### 3. Volatility-Adjusted DBC Configs (Meteora Bounty)
- HMM regime detector (3 states: low/range, mid/trend, high/cascade)
- Regime → DBC curve: calm=linear low-fee, stress=exponential high-fee
- Auto-tuned graduation thresholds for equity-like assets

### 4. 90/10 Principal-Protected Vault
- 90% deposit → low-risk yield (lending)
- 10% + yield → OTM calls on stock basket
- Floor ≈ deposit, asymmetric upside, no liquidation

### 5. Clawpump Agent Launch
- Agent token + xStock/USDC DBC pool
- 75% creator fees to agent wallet
- Stock-paired pool requirement satisfied

## Quick Start

### Prerequisites
- Rust + Anchor (`cargo install --git https://github.com/coral-xyz/anchor avm --locked --force`)
- Node.js + pnpm (`npm i -g pnpm`)
- Python 3.11+ (`pip install anchorpy solders httpx hmmlearn`)

### Devnet Deploy
```bash
# 1. Build TypeScript SDK wrapper
cd app/ts && pnpm install && pnpm run build

# 2. Build Anchor programs
cd programs/trade_audit_trail && cargo build-sbf
cd programs/trading_vault && cargo build-sbf

# 3. Deploy to devnet
anchor deploy --provider.cluster devnet

# 4. Run Python agent
cd app/agent
export RPC_URL=https://api.devnet.solana.com
export ANCHOR_PROGRAM_ID=<deployed_program_id>
export AGENT_KEYPAIR_PATH=<path_to_keypair.json>
python -m agent
```

### Environment Variables
```bash
RPC_URL=https://api.devnet.solana.com
ANCHOR_PROGRAM_ID=<trade_audit_trail_program_id>
VAULT_PROGRAM_ID=<trading_vault_program_id>
AGENT_KEYPAIR_PATH=./agent_keypair.json
CLAWPUMP_API_KEY=cpk_...  # from https://clawpump.tech/dashboard
```

## Project Structure
```
Stockulus/
├── programs/
│   ├── trade_audit_trail/     # Anchor: decision log, risk params, kill switch
│   └── trading_vault/         # Anchor: ERC4626 vault, NAV attestation
├── app/
│   ├── agent/                 # Python off-chain agent
│   │   ├── bsm.py             # Merton pricing, Greeks, IV, hedge
│   │   ├── stock_carry.py     # Carry signal + 90/10 allocation
│   │   ├── regime_hmm.py      # HMM regime detector (3 states)
│   │   ├── xstocks.py         # xStocks API adapter
│   │   ├── meteora_executor.py # TS SDK wrapper
│   │   ├── clawpump_client.py # Clawpump API wrapper
│   │   ├── execution/         # RiskGate, MultiLeg, models
│   │   └── ...
│   └── ts/                    # TypeScript DBC SDK wrapper
├── config/profiles.yaml       # Curator profiles (conservative/standard/aggressive/defensive)
├── scripts/                   # Deploy/demo scripts
└── docs/                      # EQUATIONS.md, DBC_NOTES.md, XSTOCKS_NOTES.md
```

## Submission Links
- **GitHub**: https://github.com/Henoch4/Stockulus
- **Demo Video**: [YouTube/Loom link]
- **Devnet Explorer**: [Solscan links for deployed programs]

## Team
- **Solo**: @henoch4

## Bounty Tracks Selected
- ✅ Main Track ($100,000)
- ✅ Best Use of Meteora DBC ($5,000)
- ✅ Stocknized Agent on Clawpump ($5,000)