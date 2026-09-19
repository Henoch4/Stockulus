# Stockulus — Serious Build Plan (deadline-free, Stocklana submission slice first)

**Folder:** `C:\Users\Henoch\Documents\Programming Folder\Stockulus` — **STANDALONE**.
Not a subfolder of Tarstrade. Never import from `../Tarstrade*`.
**Source to steal from (read-only):** `C:\Users\Henoch\Documents\Programming Folder\Tarstrade_extracted\Tarstrade\`
Copy files in, then edit. Submission must be self-contained.

**Hackathon:** Stocklana — https://hackathons.solana.com/hackathons/stocklana
**Deadline:** extended (was Sep 18, 2026). Plan below assumes **no deadline pressure**:
Phase A = submission slice (devnet, $0). Phase B = hardening ($0, time only).
Phase C = money-gated futures (audit, legal, mainnet capital, mobile) — parked until funded, listed honestly in §10.

**One-line product:**
> Deposit USDC → vault runs delta-neutral tokenized-stock carry (long xStock spot / short DBC leg)
> → every decision signed + logged on-chain BEFORE execution → DBC pools auto-tuned by volatility regime
> → agent launchable via Clawpump.

**Locked demo scope:** AAPLx, TSLAx, NVDAx. Quote USDC. Devnet risk: $100 max position, $20 daily loss, 1x leverage.
Vault demo: **90/10 Principal-Protected** (90% yield vault + 10% yield buys OTM calls). Covered call deferred.

---

## 1. Folder structure (already scaffolded — do not rename)

```
Stockulus/
  BUILD_PLAN.md              <- this file (audited 2026-09-17, §8 = actual states)
  README.md                  <- submission README (real IDs/txs)
  HACKATHON_SUBMISSION.md    <- track mapping + Solscan evidence
  Anchor.toml                <- LIVE devnet IDs (516a5K… audit, Gd7Ciu… vault)
  Cargo.toml                 <- workspace: programs/trade_audit_trail + trading_vault
  .env.example               <- all vars incl. QUOTE_MINT/DECIMALS, SOL_PRICE_USD, NANSEN_API_KEY
  config/profiles.yaml       <- curator allowlist (all max_leverage 1.0) DONE
  config/fee_ledger.json     <- STCKLS fee pipeline ledger (agent-appended) DONE
  config/supporters.json     <- supporters wall (goal 0.15 SOL) DONE
  programs/
    trade_audit_trail/src/lib.rs   <- Anchor audit trail — DEPLOYED 516a5KdUr5oLJTVQZaiDWxqgRSQ1xPHSvFoQbCmwVtRS
    trading_vault/src/lib.rs       <- Anchor ERC4626-style vault — DEPLOYED Gd7Ciu6KgPwoajZZgAUNethJAFNe4s3nhJV64XNRz9aF
  app/
    agent/                   <- Python off-chain agent
      bsm.py                 <- DONE: bs_price, bs_price_merton, delta_merton, greeks, greeks_merton, implied_vol, hedge_order
      stock_carry.py         <- DONE: carry_annualized, tokenized_stock_carry_signal, vault_9010_allocation, bsm_mispricing
      regime_hmm.py          <- DONE: infer_regime_simple + RegimeHMM (hmmlearn opt) + dbc_action_for_regime
      xstocks.py             <- DONE, PROBED 2026-09-17: suffix-x symbols, {"nodes"} unwrap, {"quote"} price, network-param multipliers
      meteora_executor.py    <- DONE: subprocess bridge (ts_dir path fixed)
      clawpump_client.py     <- DONE + LIVE: key verified, agent Stockulus returned, list unwrap fixed
      audit_logger_sol.py    <- DONE + LIVE: parsed Idl, Context obj, snake_case, systemProgram, initialize(); init+params+decision+receipt all confirmed on-chain
      agent.py               <- DONE + LIVE: full cycle proven (signal→risk→audit→swap→record); USD→wSOL conversion; pool resolution; fee hook
      signals.py             <- DONE (carry registered in ensemble path)
      execution/models.py    <- DONE
      execution/risk_gate.py <- DONE: earnings_blackout + blacklist + max_leverage=1.0 defaults (AAPLx/TSLAx/NVDAx)
      execution/executor.py  <- DONE: Solana rewrite (DBC swap + _verify_fill collar + kill-switch trip)
      multi_leg.py           <- DONE (generic Step; agent uses direct swap, multi_leg kept for packages)
      curator.py, data_integrity.py (+check_corporate_action), validation.py, audit_trail.py <- DONE
      dashboard.py           <- DONE: +get_fee_pipeline +get_supporters +/metrics/fees +/metrics/supporters
      __main__.py            <- DONE: explicit .env path, DRY_RUN env-gated (default true)
      requirements.txt       <- DONE
    ts/src/                  <- DONE + LIVE: create_config, create_pool, swap, quote, state, migrate, create_mint, wrap_sol, inspect_signers
  scripts/                   <- setup_credentials.sh, import_phantom_key.py, deploy_devnet.sh, demo.sh, demo_live_micro.py, test_wiring.py — all DONE
  docs/EQUATIONS.md          <- locked decisions + Merton/HMM/90-10 spec
  docs/VIDEO_SCRIPT.md       <- 2-min recording script DONE
```

**Rule:** one file, one owner at a time (§8 DAG). Never edit the same file from two parallel tasks.

---

## 2. What we steal from Tarstrade (no re-design)

| Tarstrade file | Action in Stockulus | Status |
|---|---|---|
| `src/execution/models.py` | copy verbatim | done |
| `src/execution/risk_gate.py` | copy + `earnings_blackout` + `max_leverage=1.0` default | done (blacklist + suffix-x defaults live) |
| `src/multi_leg.py` | copy verbatim | done (kept; agent uses direct swap) |
| `src/signals.py` mean_rev/momentum/funding/ensemble | copy verbatim | done |
| `src/signals.py:950 funding_carry_signal` | template for `stock_carry.py` | done |
| `src/curator.py` + `config/profiles.yaml` | copy + stock profiles | done |
| `src/validation.py` | copy verbatim | done (gate runs; OOS data is Phase C/Nansen) |
| `src/data_integrity.py` | copy + `check_corporate_action()` | done |
| `src/audit_trail.py` | copy verbatim | done |
| `contracts/TradeAuditTrail.sol` | ported to `programs/trade_audit_trail` | DEPLOYED 516a5K… (4 compile fixes + IDL sync proven live) |
| `contracts/TradingVault.sol` | ported to `programs/trading_vault` | DEPLOYED Gd7Ciu… + UPGRADED in place 2026-09-19 (slot 500668814; deposit flow PROVEN on mock USDC 9K4iVBL1…, see HACKATHON_SUBMISSION.md) |
| `ml/pipeline.py`, `features.py`, `labeling.py` | research only, post-submission; NOT demo path | parked |
| `src/execution/executor.py` OKX part | REWRITTEN as Solana executor | done (DBC swap + fill collar) |
| `src/audit_logger.py` EVM part | REPLACED by `audit_logger_sol.py` | done (init/params/decision/receipt all confirmed on-chain) |
| Do NOT port | `okx_cli.py`, OKX reconciliation, `mermail-trading-skill/`, `t3n/`, full test suite (write 5 new tests only) | — |

---

## 3. Equations — implementation (LOCKED, matches code on disk)

Papers: Black-Scholes 1973 (Princeton PDF), Merton 1973 (MIT), Merton Nobel 1997 lecture, Cornell Medallion 2020.
Video = narrative. Papers = grounding. Code below = what ships.

### 3.0 Lineage (README/video narrative, one paragraph each)
- **Bachelier:** fair-bet, pure random walk, no drift → our null model. Validation gate must beat it net of 5+3bps/side or no trade.
- **Thorp (c.1967):** random + drift. `Δ = ΔOpt/ΔStock`. Hedge portfolio `π = -V + Δ·S`. $1 up in stock = $1 loss on option + $1 gain on stock → neutral. Buy cheap / short rich vs fair value. This IS `multi_leg.py` (long xStock spot / short DBC leg).
- **BSM 1973 + Merton stochastic calculus:** hedged portfolio → risk-free → earns `r`. PDE §3.1, closed form §3.2. PDE never solved on-chain.
- **Baum/HMM → Simons/Medallion:** hidden states from observables. Medallion 1988–2018: $100→$398.7M (63.3% comp), never a down year, Sharpe >2, win 50.75% over millions of trades, beta ≈ -1. Lesson: edge = thousands of small hedged harvests + cost control (16bps hurdle, staircase slippage), not prediction. Our carry vault copies this.

### 3.1 BSM PDE (narrative only)
```
dV/dt + 0.5·σ²·S²·d²V/dS² + r·S·dV/dS − r·V = 0
V=V(S,t), S=spot, σ=vol, r=risk-free, t=time
```

### 3.2 Merton cost-of-carry closed form (IMPLEMENTED in bsm.py)
```
b = r − q − b_borrow        (r=SOL/USDC risk-free, q=div/staking yield, b_borrow=Kamino/Solend locate)
d1 = [ln(S/K) + (b + σ²/2)·T] / (σ√T),   d2 = d1 − σ√T
Call = S·e^((b−r)T)·N(d1) − K·e^(−rT)·N(d2)  =  S·e^(−(q+b_borrow)T)·N(d1) − K·e^(−rT)·N(d2)
Δ_call = e^((b−r)T)·N(d1) = e^(−(q+b_borrow)T)·N(d1)
```
Functions: `cost_of_carry()`, `bs_price_merton()`, `delta_merton()`. Classic `bs_price()` kept for tests/README parity.

### 3.3 Greeks (IMPLEMENTED: greeks() classic + greeks_merton())
```
Δ_call = disc·N(d1), Δ_put = disc·(N(d1)−1),  disc = e^((b−r)T)
Γ = disc·N'(d1)/(S·σ·√T)
Vega = disc·S·N'(d1)·√T
Theta_call = −(disc·S·N'(d1)·σ)/(2√T) − r·K·e^(−rT)·N(d2)
Theta_put  = −(disc·S·N'(d1)·σ)/(2√T) + r·K·e^(−rT)·N(−d2)
```

### 3.4 Implied vol (IMPLEMENTED: implied_vol(), Newton + bisection fallback)
Newton 50 iters on `bs_price`/`greeks.vega`, clamp σ∈[0.01,5.0], tol 1e-6; fallback bisection 50 iters.
Use: σ_IV from DBC pool price vs xStocks oracle → vol regime + mispricing scanner input.

### 3.5 Delta-hedge loop (IMPLEMENTED: hedge_order() + 45s anti-hysteresis in agent)
```
Target: hold Δ shares per 1 short call.
Rebalance when |Δ_now − Δ_held| > band (0.05) AND spread persists >45s.
hedge_order(delta_now, delta_held, notional, band) → {side, size_usd} or None
Maps to multi_leg Step(venue="meteora", action="swap", asset=stock_mint).
```

### 3.6 Tokenized-stock carry (IMPLEMENTED: stock_carry.py)
```
Carry_ann = div_yield + borrow_rate − funding − fee_drag        (decimal; ×10000 = bps)
Basis_bps = (perp_or_dbc − spot)/spot × 10000
LONG spot + SHORT DBC when carry > min_carry (50bps) AND |basis| > min_basis (5bps)
  (SHORT direction when carry negative: short spot / long DBC)
Confidence = min(0.7 + |basis_bps|/200 + |carry_ann|/200, 0.9)
```
Inputs: xStocks price-data (spot) + multiplier (div/split → div_yield), DBC sqrt_price (perp leg), oracle borrow proxy, fee_drag from DBC fee metrics.

### 3.7 DBC segment math (from docs.meteora.ag/core-products/dbc/formulas — used in dbc_config)
```
x·y = k per segment; L = liquidity, √P = sqrt(price)
Base_out  = L·(1/√P_lo − 1/√P_hi)
Quote_in  = L·(√P_hi − √P_lo)
MigrationThreshold = Σ L_i·(√P_i − √P_{i−1});  migratable when QuoteReserve ≥ Threshold
MigrationPrice = (√P_mig)²
TotalFee = BaseFee + DynamicFee (cap 99% = 990_000_000/1e9)
DynamicFee = ceil((VolAcc·BinStep)²·VarFeeControl / 1e11)
ProtocolFee = TotalFee·20%; Referral = ProtocolFee·20%
Surplus = QuoteReserve − Threshold → 80% partner+creator, 20% protocol
```
Use: choose L_i and √P grid so Threshold ≈ 750 USDC for stock/USDC pools (keeper threshold).

### 3.8 Awaiting your refs (docs/EQUATIONS.md placeholders — feed anytime, no blocking)
(a) exact dividend/borrow formula variant you want (American exercise? discrete divs?),
(b) HMM transition priors / feature windows,
(c) structured-product payoff beyond 90/10.
Each fills one function without touching other files (§8: T-regime, T-carry tasks are file-isolated).

### 3.9 90/10 Principal-Protected (IMPLEMENTED: vault_9010_allocation())
```
Deposit D. 0.9D → yield (r_y). 0.1D + yield → OTM calls on basket.
Payoff_T = 0.9D·(1+r_y·T) + N_calls·max(S_T−K,0).  Floor = 0.9D·(1+r_y·T) ≈ D.
No liquidation (no margin). Anchor vault enforces package_open guard on withdraw.
```

---

## 4. Solana / Meteora implementation (from docs, thorough)

### 4.1 Toolchain ($0, devnet)
```bash
cargo install --git https://github.com/coral-xyz/anchor avm --locked --force
avm install latest; avm use latest; solana --version; anchor --version
cd app/ts && pnpm install   # @meteora-ag/dynamic-bonding-curve-sdk, @solana/web3.js, @solana/spl-token, bn.js
cd app/agent && pip install -r requirements.txt  # anchorpy, solders, httpx, pyyaml, numpy, python-dotenv (hmmlearn optional)
solana-keygen new -o ./agent_keypair.json   # THROWAWAY devnet key only
solana airdrop 2 --url devnet
```
RPC: devnet `https://api.devnet.solana.com`. Faucet: https://faucet.solana.com. Explorer: Solscan/SolanaFM (devnet).

### 4.2 Program IDs + mints (LIVE devnet values)
```
Stockulus programs (devnet, verified executable via RPC):
  TradeAuditTrail: 516a5KdUr5oLJTVQZaiDWxqgRSQ1xPHSvFoQbCmwVtRS
  TradingVault:    Gd7Ciu6KgPwoajZZgAUNethJAFNe4s3nhJV64XNRz9aF
DBC program (mainnet == devnet): dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN
Pool authority PDA: FhVo3mqL8PW5pH5U2CN4XE33DokiyZnUwuGpH2hmHLuM
wSOL: So11111111111111111111111111111111111111112 (9dp, devnet quote — no Circle USDC on devnet)
USDC mainnet: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v (6dp; that address on devnet is a wrong-program account — unusable)
DBC config (Token-2022, calm linear): 3WDNBkpE67v2wzMWY1mgyyAuE4eugFBbgniRa1tqojFY
Pools: dAAPLx CVrD4X…vvPUU · dTSLAx 84B8P2…wDEsU · dNVDAx EebJJc…2FhqdH (all vs wSOL)
DAMM v2 fee key #6 (customizable, for mainnet stocks): A8gMrEPJkacWkcb3DGwtJwTe16HktSEfvwtuDh2MCtck
```
Devnet quote = wSOL (`QUOTE_MINT`/`QUOTE_DECIMALS=NINE` env; mainnet flips to USDC/SIX).
No xStocks exist on devnet (verified) → demo mints (`dAAPLx`, Token-2022/8dp, keypairs in `app/ts/mint-*.json`, gitignored).
Real xStocks: Token-2022 + transferHook/pausable/scaled-UI (mainnet AAPLx probed) → mainnet pools need the transfer-hook DBC path (Phase C).

### 4.3 DBC accounts (touch only these)
```
PoolConfig (new Keypair signer via create_config): quote_mint, fee_claimer, leftover_receiver,
  pool_fees{base_fee, dynamic_fee}, migration_option=1 (DAMMv2), activation_type=1 (timestamp),
  token_decimal/type, migration_quote_threshold, sqrt_start_price, curve[≤20]
VirtualPool (PDA from quote+base+config): pool_state{config, creator, base_mint, base_vault, quote_vault,
  base_reserve, quote_reserve, sqrt_price, activation_point, migration_progress, is_migrated,
  volatility_tracker, fees...}
Base/Quote vaults (PDA token accounts)
TokenBadge (PDA ["token_badge", quote_mint]) — SKIP for USDC (permissionless)
```
Reads: SDK `StateService.getPoolConfig` / `getPoolState`. Deprecated flat `pool.config` → use `pool.poolState.config`.
Our files: `app/ts/src/state.ts` (reads), `quote.ts` (quote), rest write.

### 4.4 DBC instructions (4 for demo, skip the rest)
| Need | Instruction | SDK call | Our file |
|---|---|---|---|
| partner config | `create_config(ConfigParameters)` — MigrationOption::DAMMv2, BaseFeeMode linear/exponential, fee 25–9900bps | `client.partner.createConfig(...)` | `create_config.ts` DONE + LIVE (Token-2022 config `3WDNBk…`, `TOKEN_TYPE`/`BASE_DECIMALS` env) |
| launch pool | `initialize_virtual_pool_with_token2022` — base=mint whose KEYPAIR SIGNS (program allocates+inits it), quote=wSOL devnet | `client.creator.createPool(...)` | `create_pool.ts` DONE + LIVE (3 pools; `create_mint.ts` saves mint keypairs) |
| trade | `swap2(SwapParameters2)` — mode 0 exact-in | `client.pool.swap2(...)` | `swap.ts` DONE + LIVE (29,699 dAAPLx fill verified; `QUOTE_DECIMALS` scaling) |
| graduate | `migration_damm_v2` | `client.migration.migrateToDammV2(...)` or keeper auto or migrator.meteora.ag | `migrate.ts` DONE (untriggered — pools below threshold) |
Skip for submission: transfer-hook, lockers, surplus withdraw, operator, claim-fees (wire later, Phase C).
`SwapParameters2`: amount_0 = in (exact-in) / out (exact-out), amount_1 = min-out / max-in, swap_mode 0/1/2.
Near 750 USDC threshold use PartialFill to avoid failed swaps.

### 4.5 Vol-adjusted DBC config generator (Meteora bounty core)
TS pattern (from docs.meteora.ag/developer-guides/dbc/typescript-sdk/examples — use verbatim, only params change):
- Imports: `DynamicBondingCurveClient, ActivationType, BaseFeeMode, buildCurveWithCustomSqrtPrices, CollectFeeMode, createSqrtPrices, MigrationOption, MigrationFeeOption, TokenDecimal, TokenType, TokenAuthorityOption` from SDK; `Connection, Keypair, PublicKey` from web3.js.
- STOCK curve: 3–4 sqrt_price points, quote=wSOL devnet (9dp) / USDC mainnet (6dp) via `QUOTE_DECIMALS`, base=Token-2022 8dp via `BASE_DECIMALS` (mirrors xStocks); token program via `TOKEN_TYPE` (default Token2022).
- Calm (regimeScale>0.9): `FeeSchedulerLinear`, startingFeeBps 120 → ending 100, 60 periods, 3600s.
- Stress (regimeScale≤0.9): `FeeSchedulerExponential`, startingFeeBps 900 → ending 100.
- Always: `dynamicFeeEnabled=true`, `collectFeeMode=QuoteToken`, `creatorTradingFeePercentage=50`.
- Migration: `MET_DAMM_V2`, `Customizable`, fee 10%, creator 50%, migratedPoolFee 100bps.
- Liquidity: partner 0% / partner-permanent-lock 100% (no creator skim for demo).
- `liquidityWeights: [2,1,1]`, `activationType: Timestamp`.
- Python `dbc_config.py` superseded: regime→config is a `regimeScale` argv (`create_config.js 1.0` calm) — no mirrored module needed; HMM regime selects the arg.
- `createConfig`: config=Keypair.generate() signer + feeClaimer + leftoverReceiver + payer + quoteMint=wSOL(devnet)/USDC(mainnet).
- `createPool`: baseMint=xStock mint, config, name/symbol/uri, payer, poolCreator; pool=`deriveDbcPoolAddress(USDC, baseMint, config)`.
- `swap2`: swapBaseForQuote=false (buy base with USDC), ExactIn, slippageBps 100.
- Progress: `getPoolQuoteTokenCurveProgress` + `getPoolFeeMetrics` + `getPoolFeeBreakdown`.

### 4.6 Anchor program 1: trade_audit_trail (BUILT + DEPLOYED 516a5K…)
Port of `TradeAuditTrail.sol` → Anchor, ed25519 agent. All 5 items proven live:
init tx `fbD3Sx…`, risk-params txs, `log_decision` (`dec_0ff8e8bb4d80`) + execution receipt.
Compile fixes banked: `#[instruction]` seeds, String clones. `Anchor.toml` + `declare_id!` carry live IDs.
Python logger: parsed `Idl` + `Context` + snake_case + systemProgram + `initialize()`; log BEFORE execute, RPC failure blocks trade.

### 4.7 Anchor program 2: trading_vault (BUILT + DEPLOYED Gd7Ciu… + UPGRADED in place 2026-09-19, slot 500668814; deposit flow PROVEN on mock USDC — see HACKATHON_SUBMISSION.md)
`initialize` (owner/agent/mint/caps), `deposit` (min/max checks, USDC transfer in, pro-rata share mint),
`withdraw` (blocked when `package_open`, burn + transfer out), `attest_total_assets` (agent-only, max TVL, delta cap),
`set_package_open` (agent-only). Deployed via CI; deposit/withdraw flow PROVEN 2026-09-19 on mock SPL USDC (no devnet Circle USDC): init 2iPxDG6… + deposit CXwCf9As… + attest 65yZcSHE… + timelock/delta-cap expected-fail probes + withdraw 3Rf2BHV1… to zero.

### 4.8 Python Solana executor + audit logger (BUILT + PROVEN on devnet)
- `meteora_executor.py`: subprocess `node app/ts/dist/<script>.js`, JSON stdout, 60s timeout; ts_dir path fixed; USD→wSOL conversion via `SOL_PRICE_USD` (Pyth feed Phase C).
- `audit_logger_sol.py`: parsed `Idl.from_json` + `Context` + snake_case accounts + systemProgram/agentState completeness + `initialize()`; `log_decision` BEFORE executor call; RPC failure → block trade. Keypair loader accepts solana-keygen JSON (was hex-only).

---

## 5. xStocks / Backpack / Sunrise implementation

Base `https://api.xstocks.fi/api/v2` (public, no key). Implemented in `app/agent/xstocks.py` (DONE, PROBED 2026-09-17):
```
GET /public/assets → {"nodes": [...100/page]} (symbols are SUFFIX-x: AAPLx/TSLAx/NVDAx)
GET /public/assets/{sym} → node incl. deployments[] (Solana mint: AAPLx XsbE…csP5)
GET /public/assets/{sym}/price-data → {"quote": float} (normalized to {"price"})
GET /public/assets/{sym}/multiplier?network=Solana → {"currentMultiplier"} (AAPLx 1.00327)
GET /public/assets/{sym}/multiplier/history?network=Solana → {"nodes": [{reason: Dividend, ...}]} → div_yield proxy
GET /public/corporate-actions/upcoming → {"nodes": [{xstockSymbol, caType, effectiveTimeUtc}]} → blackout map
GET /public/oracles/{sym} → {"nodes": [{feedId (Pyth hex), decimals}]} 
GET /public/proof-of-reserves/{sym} → {sharesHeld, circulatingSupply} (AAPLx ratio 1.002)
```
Live spot (quote×mult): AAPLx 337.24, TSLAx 366.47, NVDAx 219.72. Solana = Token-2022 + Scaled UI.
Solana specifics: SPL Token-2022 + Scaled UI extension. Raw balance constant; apply multiplier off-chain.
Demo symbols: AAPLx, TSLAx, NVDAx (resolve exact mints via `get_solana_mint` at runtime, cache JSON for offline demo).
Backpack/Sunrise (https://docs.sunrise.xyz/equities/backpack-securities): 1:1 redeemable real shares narrative
("backed + convertible via Backpack, tradable 24/7 via Sunrise"). No API key for demo; link conversion flow in README.

---

## 6. Clawpump implementation (bounty #2 — KEY WIRED, agent live, launch pending funding)

Docs: https://clawpump.tech, dashboard. Implemented in `clawpump_client.py` (DONE + LIVE):
- `cpk_` key in `.env`, verified: `list_agents` returns agent `Stockulus` (`756d9f58-…`), wallet `BaSrnkuqZ1hWY9i9L6RrhKm6wRV5Pi3f81brxxk2nnGc`
- `list_agents` unwraps `{"agents": [...]}`; explicit `.env` path (bare load_dotenv misses on Windows — fixed in `__main__.py` too)
- Launch: STCKLS via dashboard or `launch_token` (agent wallet needs ~0.15 SOL: launch + pool + buffer)
- Fee loop: 75% creator fees → agent wallet → `config/fee_ledger.json` + `/metrics/fees` (SHIPPED)

---

## 7. Agent loop wiring (BUILT + PROVEN — `scripts/demo_live_micro.py`, $5 cap, all txs real)

```
xstocks.get_spot_price (live) → carry signal (live div proxy) → regime → curator
  → data_integrity → risk_gate.check_order (pool allowlist) → audit log_decision (BLOCK on fail)
  → USD→wSOL conversion → meteora.swap → audit record_execution → fee-ledger append
```
Proven 2026-09-17: init `fbD3Sx…` + params + decision `dec_0ff8e8bb4d80` + swap `AvubGL…` (+29,699 dAAPLx).
Bugs banked: audit `package_id`, DBC pool env resolution, dry-run default true, executor ts_dir.

---

## 8. Parallel build DAG (file-collision-free)

### P0 — 6 tasks, all parallel, no shared files (scaffold/copies/math/reads)
| ID | Task | Output file(s) | Needs | State |
|---|---|---|---|---|
| T1 | Folders + Anchor init + TS pkg + Python pkg | tree §1 | nothing | DONE |
| T2 | Copy Tarstrade verbatim (models, multi_leg, curator, validation, data_integrity, audit_trail, signals, agent, profiles) | `app/agent/*`, `config/` | read-only Tarstrade_extracted | DONE → verify |
| T3 | `bsm.py` pure math + tests | `app/agent/bsm.py` | nothing | DONE |
| T4 | `xstocks.py` + cache sample JSON | `app/agent/xstocks.py`, `docs/xstocks_sample.json` | public API | DONE code → cache sample |
| T5 | TS read-only: connection + getPoolConfig/State + quote | `app/ts/src/state.ts, quote.ts` | devnet RPC | DONE stub → verify |
| T6 | Anchor skeletons compile | `programs/*/src/lib.rs` | T1 dirs | DONE → `anchor build` verify |

### P1 — actual outcomes (built live, not as specced — deltas noted)
| ID | Task | Outcome |
|---|---|---|
| T7 | AuditTrail verify + IDL + program ID | DONE + DEPLOYED 516a5K… (hand-IDL + anchorpy Context fixes proven on-chain) |
| T8 | Vault verify + IDL + program ID | DONE + DEPLOYED Gd7Ciu… + UPGRADED in place 2026-09-19 (slot 500668814; deposit flow PROVEN on mock USDC 9K4iVBL1…, see HACKATHON_SUBMISSION.md) |
| T9 | carry + regime + DBC config | DONE (dbc_config.py superseded: regime→`regimeScale` argv in create_config.js) |
| T10 | TS scripts + devnet pools | DONE ×3 (config `3WDNBk…`, dAAPLx/dTSLAx/dNVDAx pools, live swaps; +wrap_sol/create_mint/inspect_signers) |
| T11 | audit logger + executor + risk/integrity | DONE (all proven in T13 live cycle) |

### P2 — actual outcomes
| ID | Task | State |
|---|---|---|
| T12 | Wire loop §7 | DONE (tested: 3/3/3 offline; live $5 cycle fully on-chain) |
| T13 | Devnet demo + audit query | DONE (init/params/decision/swap/receipt/vault-loop txs banked; vault loop proven on mock USDC) |
| T14 | README + submission + video + submit | DOCS DONE (real IDs/txs, VIDEO_SCRIPT.md); VIDEO + SUBMIT open (human) |

**Collision rule:** P0/P1 parallel OK (disjoint files). P2 single-threaded. `git status` clean between tasks.

---

## 9. Submission checklist (actual, 2026-09-17)
- [x] GitHub: https://github.com/Henoch4/Stockulus (public, pushed)
- [x] Live devnet demo (evidence table in HACKATHON_SUBMISSION.md — every row Solscan-linked)
- [x] Main track: vault (deployed) + carry (live signal) + audit trail (live receipts)
- [x] DBC bounty: Token-2022 config + 3 pools + verified swaps + regime-tuned fee code
- [ ] Clawpump bounty: agent live + key wired; token launch pending ~0.15 SOL funding
- [ ] Video walkthrough (script: `docs/VIDEO_SCRIPT.md` — needs voice/screens, human)
- [ ] Submit Project on hackathons.solana.com (human)
- [x] Solo team (@henoch4)

---

## 10. Money-gated futures (Phase C — parked, honest, post-submission)

These do NOT block submission. They need money, not just time:

| Item | Cost | Why gated |
|---|---|---|
| Professional audit (2 contracts, lean/Sherlock tier) + fix-verification | $8–20K | Required before strangers deposit (Tarstrade mainnet-roadmap Phase 4) |
| Bug bounty (Immunefi-style, capped) | $5–10K | After audit |
| Legal memo (single jurisdiction, fund/adviser analysis) + fee-structure decision | $3–8K | Before opening past colleagues (Phase 5); can end project if skipped |
| Persistent host (VPS/container, scheduler, RISK_STATE_PATH) | $5–20/mo | Serverless contradicts multi-leg state + WS hub + counters |
| Mainnet deploy + liquidity + gas + paymaster | gas + TVL + sponsorship | Devnet demo is free; mainnet needs real USDC + keeper fees |
| First-loss operator tranche | personal stake | Biggest trust lever for real depositors (Phase 6) |
| Mobile app (Expo, Google Pay primary / Apple Pay companion, passkey wallet, NIP/DVA Nigeria rail) | dev + store + onramp fees | Phase 8 distribution; same vault, new onramp |
| Multi-chain inbound (Base CCTP first, Solana verify receive) | bridge + audit delta | Phase 9; vault stays on Solana |
| Paid data feeds (borrow/locate, low-latency oracles) | subscription | xStocks public API suffices for demo |
| Nansen on-chain intelligence (Smart Money + Token God Mode) | API key or x402 ~$0.01/query USDC on Solana | Key/money-gated; Phase A cites as source, Phase C wires it — see §10.1 |

**Non-negotiable order (from Tarstrade roadmaps):** prove carry on majors one validated quarter → alts → personal satellite → tokenized stocks scale → mobile. Never let deposit caps get ahead of verified safety. Audit + legal before anyone beyond personally-briefed colleagues deposits.

---

### 10.1 Phase C: Nansen on-chain intelligence (key/money-gated)

Source: Nansen API (`https://api.nansen.ai`, docs `https://docs.nansen.ai/api`, key in `apikey` header)
+ Nansen Meridian Buildathon Sep 14–27 (second submission venue for the same agent).
Access: API key, or x402 pay-per-call ~$0.01/query in USDC on Base/Solana via `nansen-cli` (`github.com/nansen-ai/nansen-cli`, skills e.g. `nansen-token-screener`).

**Why:** Tarstrade's `onchain_flow_signal(asset, whale_net_flow_usd, exchange_reserve_change_pct, stablecoin_supply_change_pct)`
already expects exactly what Nansen serves — and `smartmoney_signal` is dead code waiting for a real feed.
Phase A ships with neutral defaults; README cites Nansen as the Phase C source. No signal redesign needed later.

| Nansen endpoint | Feeds | Notes |
|---|---|---|
| Smart Money Netflows (accumulation/distribution) | `onchain_flow_signal` whale leg | Resurrects dead `smartmoney_signal` |
| Smart Money Holdings + Historical Holdings | carry confirmation + `validation.py` OOS | "Are smart traders accumulating this xStock?" |
| Token God Mode Holders / Flows / Who Bought-Sold | `stock_carry.py` crowding check + `regime_hmm` basis feature | Holder concentration = carry-collapse warning (EXPANSION scream-filter pattern) |
| Token Screener (5m–30d, volume/liquidity/mcap/smart-money) | `curator.py` universe selection | Only list xStocks liquid enough to clear the 16bps hurdle net of slippage |
| Historical OHLCV / DEX Trades / Flow Summary | `validation.py` gate + triple-barrier labels | Solana-leg history so Calmar/PBO means something on tokenized stocks |
| Profiler Labels + Balances | `data_integrity.py` + RiskGate allowlist | DBC creator checks (rugger/exchange labels); exchange-reserve leg |
| Smart Alerts (Telegram/Slack/Discord) | `alerting.py` | Deterministic pivot triggers (rule-based, not learned) |
| PnL Leaderboard | dashboard + curator | Reference carry wallets; copy-trading wedge for consumer track |

**Phase C build (SHIPPED, docs-verified, key-activates):** `app/agent/nansen.py` — direct REST
(`httpx`, mirrors `xstocks.py`), NOT the CLI wrapper. Exact paths (docs.nansen.ai OpenAPI):
`POST /api/v1/token-screener` (1cr), `/api/v1/smart-money/netflow` (5cr),
`/api/v1/smart-money/holdings` (5cr), `/api/v1/tgm/flow-intelligence` (1cr),
`/api/v1/tgm/indicators` (5cr, daily batch). Chain slugs lowercase (`solana`).
Budget discipline: `X-Nansen-Credits-Remaining` tracked per call, `NANSEN_MIN_CREDITS`
floor (default 20) fail-closed, 429 honors Retry-After once, insufficient/plan codes
latch off for the session. Labels endpoint (100/500cr) never called.
Mappings: flow record → `onchain_flow_inputs()`; concentration-risk high →
`concentration_flag()`; screener liquidity/volume → curator universe.
24h file cache (6h flow). Verified neutral without key; LIVE 2026-09-18 on real mainnet
AAPLx: whale +$27.4K, smart_trader −$55, exchange +$295K inflow (distribution read),
mapping + concentration check correct, 6 credits spent (100→94, Free plan).
Wire order: netflows → `onchain_flow_signal` → ensemble; historical → validation OOS; alerts → `alerting.py`.
`.env` addition: `NANSEN_API_KEY=` (or x402 wallet path). Never commit the key (gitleaks CI).

---

## 11. What to feed me next (equation refs — non-blocking)

Drop into `docs/EQUATIONS.md`: (a) BSM variant (American? discrete divs?), (b) HMM priors/windows,
(c) structured payoff beyond 90/10. Each fills ONE function (§3.8). Build proceeds without them.

*End — audited 2026-09-17. Open human items only: STCKLS funding (~0.15 SOL) → launch,
video record (VIDEO_SCRIPT.md) → Submit Project. Next code: dTSLAx/dNVDAx seed swaps (dust).*
