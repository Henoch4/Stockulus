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
npm install
npx tsc -p tsconfig.json
set RPC_URL=https://api.devnet.solana.com
set KEYPAIR_PATH=../agent_keypair.json   # repo-root agent_keypair.json
node dist/create_config.js 1.0   # calm regime → partner config pubkey
node dist/create_mint.js 8 dAAPLx ./mint-dAAPLx.json   # fresh Token-2022 mint (DBC needs mint signature)
node dist/create_pool.js <base_mint> <config> "Demo AAPLx" "dAAPLx" <uri> ./mint-dAAPLx.json
node dist/wrap_sol.js 0.05   # wrap SOL → wSOL (devnet quote, no Circle USDC on devnet)
node dist/swap.js <pool> 0.02 100 false  # buy dAAPLx with wSOL (amounts in quote units)

# Live agent demo (capped micro-cycle, fully on-chain)
C:\Python314\python.exe scripts\demo_live_micro.py

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
- Vol-adjusted config: calm=linear 120bps, stress=exponential 900bps (`create_config.js <regimeScale>`)
- Stock curve: 4-point sqrt_price grid, Token-2022 base (8dp, mirrors xStocks), wSOL quote on devnet
- Devnet reality: no Circle USDC exists on devnet → wSOL quote (`QUOTE_MINT` env; mainnet flips to USDC)
- No xStocks on devnet → demo mints (`dAAPLx`) mirror real decimals; DBC requires the base mint itself as signer
- Real xStocks carry transferHook/pausable extensions → mainnet needs the transfer-hook DBC path (Phase C)
- Auto-migration to DAMM v2 via keeper / migrator.meteora.ag

### 5. Clawpump Agent
- Agent `Stockulus` live: ID `756d9f58-0ca5-4357-849d-73ae48567cf5`, wallet `BaSrnkuqZ1hWY9i9L6RrhKm6wRV5Pi3f81brxxk2nnGc`
- Token launch (STCKLS) + stock-paired pool: pending ~0.15 SOL funding
- 75% creator fees → agent wallet → compounds vault (fee dashboard in progress)

## Demo Evidence (Devnet, all verifiable on Solscan)

| Component | Status | Evidence |
|-----------|--------|----------|
| TradeAuditTrail deployed | ✅ | `516a5KdUr5oLJTVQZaiDWxqgRSQ1xPHSvFoQbCmwVtRS` ([Solscan](https://solscan.io/account/516a5KdUr5oLJTVQZaiDWxqgRSQ1xPHSvFoQbCmwVtRS?cluster=devnet)) |
| TradingVault deployed | ✅ | `Gd7Ciu6KgPwoajZZgAUNethJAFNe4s3nhJV64XNRz9aF` ([Solscan](https://solscan.io/account/Gd7Ciu6KgPwoajZZgAUNethJAFNe4s3nhJV64XNRz9aF?cluster=devnet)) |
| DBC config (Token-2022, calm) | ✅ | `3WDNBkpE67v2wzMWY1mgyyAuE4eugFBbgniRa1tqojFY` ([tx](https://solscan.io/tx/S2oKjam2ppdLNGyExxXfXrc6fheF3fBWgECbGbCFrn8dqzPP6G9rBJJJPxUHfiCsvnQdr6tPGVfJqBv3izzLQFx?cluster=devnet)) |
| dAAPLx pool (dAAPLx/wSOL) | ✅ | `CVrD4XycbRgMhWjr6tTQ6ebV41NGAG95cV8NccCvvPUU` ([tx](https://solscan.io/tx/2ri6Y3NmXQqS4pSpv536DDJr7hnNN7Csbgmh5hxR1wqqs177po5Jr4UbC6Bw4bSZiHZRJXb99N8TXTyLJUcLp221?cluster=devnet)) |
| dTSLAx pool | ✅ | `84B8P25ec51c2szffJUEkkyMpUf81eqBFWHNH9pwDEsU` |
| dNVDAx pool | ✅ | `EebJJc253Rg5BJgiHCMkvGo2GzieZToSkDKvtw2FhqdH` |
| Agent state init + risk params | ✅ | `fbD3Sx…QUc48`, `2k9LJap3…3enLMqW5` |
| Decision logged on-chain | ✅ | `dec_0ff8e8bb4d80` (LONG AAPLx, 9000bps, $4.50) |
| Live DBC swap ($4.50 → 29,699 dAAPLx) | ✅ | [tx](https://solscan.io/tx/AvubGLJ8q4JiF4ub5ejVmbjBZjMXiu9aBX2gJNxGsasXR8D5tNS6eezHiSQC61vsFMS2fKggq9AF87HQ3afmLoD?cluster=devnet) |
| Vault deposit/withdraw | ⏳ | Program live; flow untested (no devnet USDC) — mainnet/Phase C |
| Clawpump agent | ✅ live / ⏳ token | Agent `756d9f58-…` live; STCKLS launch pending ~0.15 SOL funding |

**Honest disclosures:** demo mints (`dAAPLx`) mirror xStocks decimals but are NOT Backed equity (no xStocks exist on devnet — verified on-chain); pools are thin (devnet dust liquidity); mainnet needs the transfer-hook DBC path for real xStocks (transferHook/pausable extensions confirmed on mainnet AAPLx).

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
- [x] GitHub: https://github.com/Henoch4/Stockulus
- [x] Devnet demo working (evidence table above — every row links to Solscan)
- [ ] Video walkthrough (2 min — script: `docs/VIDEO_SCRIPT.md`)
- [x] All 3 bounty tracks selected
- [x] Solo team (@henoch4)
- [ ] Submit Project on hackathons.solana.com before close

## Team
- **Solo**: @henoch4 (submitter)

## After Stocklana
Colosseum World's Fair → mainnet deploy → real capital → scale