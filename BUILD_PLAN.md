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
  BUILD_PLAN.md              <- this file
  README.md                  <- submission README
  HACKATHON_SUBMISSION.md    <- track mapping + demo links
  Anchor.toml                <- devnet program IDs (placeholder until deploy)
  Cargo.toml                 <- workspace: programs/trade_audit_trail + trading_vault
  .env.example               <- RPC_URL, ANCHOR_PROGRAM_ID, VAULT_PROGRAM_ID, AGENT_KEYPAIR_PATH, CLAWPUMP_API_KEY
  config/profiles.yaml       <- curator allowlist (conservative/standard/aggressive/defensive, all max_leverage 1.0) DONE
  programs/
    trade_audit_trail/src/lib.rs   <- Anchor audit trail (AgentState, Decision, risk params, kill switch) DONE skeleton
    trading_vault/src/lib.rs       <- Anchor ERC4626-style vault (deposit/withdraw/attest/setPackageOpen) DONE skeleton
  app/
    agent/                   <- Python off-chain agent
      bsm.py                 <- DONE: bs_price, bs_price_merton, delta_merton, greeks, greeks_merton, implied_vol, hedge_order
      stock_carry.py         <- DONE: carry_annualized, tokenized_stock_carry_signal, vault_9010_allocation, bsm_mispricing
      regime_hmm.py          <- DONE: infer_regime_simple + RegimeHMM (hmmlearn opt) + dbc_action_for_regime
      xstocks.py             <- DONE: XStocksClient (assets, price-data, multiplier, history, corporate-actions, oracles, PoR)
      meteora_executor.py    <- DONE shim: create_config/create_pool/swap/state/quote/migrate via node subprocess
      clawpump_client.py     <- DONE: agents, launch_token, earnings, swap quote/execute, balances
      audit_logger_sol.py    <- DONE shim: anchorpy TradeAuditTrail client (set_risk_params/log_decision/record_execution/kill)
      agent.py               <- PORTED (verify Solana wiring, no OKX imports)
      signals.py             <- COPIED (verify stock_carry registered in ensemble path)
      execution/models.py    <- COPY VERBATIM (generic already)
      execution/risk_gate.py <- COPY + earnings_blackout flag + default max_leverage=1.0 for stocks
      execution/executor.py  <- REPLACE OKX CLI with Solana path (RiskGate check + MeteoraExecutor.swap + _verify_fill)
      multi_leg.py           <- COPY VERBATIM (Step generic; verify Meteora Step actions)
      curator.py, data_integrity.py (+check_corporate_action), validation.py, audit_trail.py <- COPY (+ small stock adds)
      dashboard.py, __main__.py, requirements.txt <- DONE (verify)
    ts/src/                  <- DONE stubs: create_config.ts, create_pool.ts, swap.ts, quote.ts, state.ts, migrate.ts
  scripts/demo.sh, deploy_devnet.sh, test_wiring.py <- DONE (verify on devnet)
  docs/EQUATIONS.md          <- locked decisions + Merton/HMM/90-10 spec; placeholders §3.8 await your refs
```

**Rule:** one file, one owner at a time (§8 DAG). Never edit the same file from two parallel tasks.

---

## 2. What we steal from Tarstrade (no re-design)

| Tarstrade file | Action in Stockulus | Status |
|---|---|---|
| `src/execution/models.py` | copy verbatim | done/verify |
| `src/execution/risk_gate.py` | copy + `earnings_blackout` + `max_leverage=1.0` default | todo (small diff) |
| `src/multi_leg.py` | copy verbatim | done/verify |
| `src/signals.py` mean_rev/momentum/funding/ensemble | copy verbatim | done/verify |
| `src/signals.py:950 funding_carry_signal` | template for `stock_carry.py` | done |
| `src/curator.py` + `config/profiles.yaml` | copy + stock profiles | done |
| `src/validation.py` | copy verbatim | done/verify |
| `src/data_integrity.py` | copy + `check_corporate_action()` | todo (small diff) |
| `src/audit_trail.py` | copy verbatim | done/verify |
| `contracts/TradeAuditTrail.sol` | ported to `programs/trade_audit_trail` | skeleton done → audit §4.6 |
| `contracts/TradingVault.sol` | ported to `programs/trading_vault` | skeleton done → audit §4.7 |
| `ml/pipeline.py`, `features.py`, `labeling.py` | research only, post-submission; NOT demo path | parked |
| `src/execution/executor.py` OKX part | REWRITE as Solana executor | todo |
| `src/audit_logger.py` EVM part | REPLACED by `audit_logger_sol.py` | shim done → IDL sync |
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

### 4.2 Program IDs + mints
```
DBC program (mainnet == devnet): dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN
Pool authority PDA: FhVo3mqL8PW5pH5U2CN4XE33DokiyZnUwuGpH2hmHLuM
USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v  (keeper threshold 750 USDC)
wSOL: So11111111111111111111111111111111111111112  (10 SOL threshold)
DAMM v2 fee key #6 (customizable, use for stocks): A8gMrEPJkacWkcb3DGwtJwTe16HktSEfvwtuDh2MCtck
```
Stock quote pairs: keepers migrate stock-token quotes when threshold ≥ 750 USD equiv → set `migration_quote_threshold` = 750 USDC worth.

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
| partner config | `create_config(ConfigParameters)` — MigrationOption::DAMMv2, BaseFeeMode linear/exponential (NOT rate-limiter for demo), fee 25–9900bps | `client.partner.createConfig(...)` | `create_config.ts` DONE stub → verify params §4.5 |
| launch pool | `initialize_virtual_pool_with_spl_token` — base=xStock mint, quote=USDC, Metaplex metadata | `client.creator.createPool(...)` | `create_pool.ts` DONE stub → verify |
| trade | `swap2(SwapParameters2)` — mode 0 exact-in | `client.pool.swap2(...)` | `swap.ts` DONE stub → verify |
| graduate | `migration_damm_v2` | `client.migration.migrateToDammV2(...)` or keeper auto or migrator.meteora.ag | `migrate.ts` DONE stub → verify |
Skip for submission: transfer-hook, lockers, surplus withdraw, operator, claim-fees (wire later, Phase C).
`SwapParameters2`: amount_0 = in (exact-in) / out (exact-out), amount_1 = min-out / max-in, swap_mode 0/1/2.
Near 750 USDC threshold use PartialFill to avoid failed swaps.

### 4.5 Vol-adjusted DBC config generator (Meteora bounty core)
TS pattern (from docs.meteora.ag/developer-guides/dbc/typescript-sdk/examples — use verbatim, only params change):
- Imports: `DynamicBondingCurveClient, ActivationType, BaseFeeMode, buildCurveWithCustomSqrtPrices, CollectFeeMode, createSqrtPrices, MigrationOption, MigrationFeeOption, TokenDecimal, TokenType, TokenAuthorityOption` from SDK; `Connection, Keypair, PublicKey` from web3.js.
- STOCK curve: 3–4 sqrt_price points, quote=USDC (6dp), base=xStock (check mint decimals via `get_solana_mint`).
- Calm (regimeScale>0.9): `FeeSchedulerLinear`, startingFeeBps 120 → ending 100, 60 periods, 3600s.
- Stress (regimeScale≤0.9): `FeeSchedulerExponential`, startingFeeBps 900 → ending 100.
- Always: `dynamicFeeEnabled=true`, `collectFeeMode=QuoteToken`, `creatorTradingFeePercentage=50`.
- Migration: `MET_DAMM_V2`, `Customizable`, fee 10%, creator 50%, migratedPoolFee 100bps.
- Liquidity: partner 0% / partner-permanent-lock 100% (no creator skim for demo).
- `liquidityWeights: [2,1,1]`, `activationType: Timestamp`.
- Python `dbc_config.py` (new, ~60 lines) mirrors this and outputs JSON → TS creates config. Demo shows calm vs stress configs side-by-side.
- `createConfig`: config=Keypair.generate() signer + feeClaimer + leftoverReceiver + payer + quoteMint=USDC.
- `createPool`: baseMint=xStock mint, config, name/symbol/uri, payer, poolCreator; pool=`deriveDbcPoolAddress(USDC, baseMint, config)`.
- `swap2`: swapBaseForQuote=false (buy base with USDC), ExactIn, slippageBps 100.
- Progress: `getPoolQuoteTokenCurveProgress` + `getPoolFeeMetrics` + `getPoolFeeBreakdown`.

### 4.6 Anchor program 1: trade_audit_trail (skeleton DONE → verify these 5 items)
1. `initialize` creates `AgentState` PDA `["agent_state", agent]` (done).
2. `set_risk_params` tightening-only (done).
3. `log_decision` checks kill_switch, size ≤ max_position, confidence ≥ floor, daily bucket rollover, trades<100, loss<cap; writes `Decision` PDA `["decision", decision_id]`; emits `DecisionLogged` (done).
4. `record_execution` owner-check + direction-aware loss (done).
5. Kill-switch activate/deactivate (done).
Remaining: `anchor build` + `anchor test` on devnet; export IDL → sync `audit_logger_sol.py` IDL const (field-for-field); replace placeholder program ID in `Anchor.toml` after `anchor deploy --provider.cluster devnet`.

### 4.7 Anchor program 2: trading_vault (skeleton DONE → verify these 4 items)
`initialize` (owner/agent/mint/caps), `deposit` (min/max checks, USDC transfer in, pro-rata share mint),
`withdraw` (blocked when `package_open`, burn + transfer out), `attest_total_assets` (agent-only, max TVL, delta cap),
`set_package_open` (agent-only). Remaining: `anchor build/test/deploy`; single-step withdraw is the demo (two-step request→finalize is Phase C).

### 4.8 Python Solana executor + audit logger (shims DONE → verify on devnet)
- `meteora_executor.py`: subprocess `node app/ts/dist/<script>.js`, JSON stdout, 60s timeout. Keep agent loop unchanged.
- `audit_logger_sol.py`: anchorpy `Program(IDL, program_id, provider)`; `log_decision` BEFORE executor call; RPC failure → block trade (same guarantee as EVM version). Verify keypair load path matches `AGENT_KEYPAIR_PATH` format (solana-keygen JSON array).

---

## 5. xStocks / Backpack / Sunrise implementation

Base `https://api.xstocks.fi/api/v2` (public, no key). Implemented in `app/agent/xstocks.py` (DONE):
```
GET /public/assets → list (symbol, Solana mint, decimals, name)
GET /public/assets/{sym}/price-data → {price, source: onchain|nasdaq-blueocean}
GET /public/assets/{sym}/multiplier → {current, pending} (display = raw × mult)
GET /public/assets/{sym}/multiplier/history → splits/divs → div_yield input
GET /public/corporate-actions/upcoming → earnings/div calendar → risk_gate earnings_blackout
GET /public/oracles/{sym} → oracle PDAs per network
GET /public/proof-of-reserves/{sym} → backing check for dashboard
```
Solana specifics: SPL Token-2022 + Scaled UI extension. Raw balance constant; apply multiplier off-chain.
Demo symbols: AAPLx, TSLAx, NVDAx (resolve exact mints via `get_solana_mint` at runtime, cache JSON for offline demo).
Backpack/Sunrise (https://docs.sunrise.xyz/equities/backpack-securities): 1:1 redeemable real shares narrative
("backed + convertible via Backpack, tradable 24/7 via Sunrise"). No API key for demo; link conversion flow in README.

---

## 6. Clawpump implementation (bounty #2, Day-4-gated on API key)

Docs: https://clawpump.tech, https://agents.clawpump.tech, npm `clawpump`. Implemented in `clawpump_client.py` (DONE):
```bash
npx clawpump launch --paid
npx clawpump create "Stockulus Stock Agent"
```
API (needs `cpk_` key — money-gated if paid launch required):
```
POST /api/v1/agents → {id, wallet}
POST /api/v1/launch {agent_id, name, ticker, quote_mint: USDC, meteora_config} → {mint, pool}
GET /api/agents/:id/earnings → creator fees (75% eligible)
```
Flow: Clawpump launch (base=STCKLS token) → Meteora DBC pool (base vs quote USDC or xStock mint)
→ Python agent trades carry → fees accrue → dashboard shows earnings.
"Stock-paired" satisfied by quote=xStock mint OR base=stock-tracker token + carry strategy labelled stock-paired.
No key → demo with recorded API responses + CLI transcript (still submittable; bounty needs live tx).

---

## 7. Agent loop wiring (P2, single-threaded)

```
xstocks.get_spot_price → meteora_executor.get_pool_state (perp/dbc price)
  → stock_carry.tokenized_stock_carry_signal + bsm.bsm_mispricing (scanner)
  → regime_hmm.predict → curator profile → dbc_config (if regime changed)
  → data_integrity (staleness + corporate-action blackout)
  → risk_gate.check_order → audit_logger_sol.log_decision (BLOCK on fail)
  → meteora_executor.swap → audit_logger_sol.record_execution
  → vault attest_total_assets (NAV) → dashboard update
```
Files touched: `agent.py`, `execution/executor.py`, `__main__.py`, `dashboard.py` only.

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

### P1 — 5 tasks, each needs ONE P0 output, disjoint files → parallel
| ID | Task | Needs | Output | State |
|---|---|---|---|---|
| T7 | AuditTrail full verify + `anchor test` + export IDL | T6 | program + IDL + program ID | skeleton done |
| T8 | Vault full verify + `anchor test` + export IDL | T6 | program + IDL + program ID | skeleton done |
| T9 | `stock_carry.py` + `regime_hmm.py` + NEW `dbc_config.py` | T2+T3+T4 (read) | signals + config JSON | 2/3 done → write dbc_config.py |
| T10 | TS create_config + create_pool + swap2 + migrate verify on devnet | T5 | working scripts + 1 devnet pool | stubs done → verify |
| T11 | `audit_logger_sol.py` IDL sync + `meteora_executor.py` verify + risk_gate earnings flag + data_integrity corporate check | T2 | solana glue | shims done → small diffs |

### P2 — integration, sequential, 1 agent (needs P1)
| ID | Task | Needs | State |
|---|---|---|---|
| T12 | Wire loop §7 + 5 tests (bsm, carry, regime, risk_gate earnings, multi_leg Meteora step) | T7+T9+T10+T11 | todo |
| T13 | Devnet deploy + demo (pool + 1 carry package + vault deposit→attest→withdraw + audit query) | T12+T8 | todo |
| T14 | README + HACKATHON_SUBMISSION + video script + submit | T13 | drafts done → finalize with real tx hashes |

**Collision rule:** P0/P1 parallel OK (disjoint files). P2 single-threaded. `git status` clean between tasks.

---

## 9. Submission checklist
- [ ] Registered + Submit Project (edits allowed until close)
- [ ] GitHub link + live devnet demo (mainnet preferred — Phase C) + video (2–3 min)
- [ ] Main track: vault + carry + audit trail (§4.6–4.8 + §7)
- [ ] DBC bounty: `dbc_config.py` + calm/stress configs + pool + README "Best Use of DBC"
- [ ] Clawpump bounty: agent launch + stock-paired pool tx + earnings screenshot (or recorded transcript if key gated)
- [ ] Solo team; invite teammates from submit form if any

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

**Phase C build (one file, env-gated):** `app/agent/nansen.py` (~80 lines, mirrors `xstocks.py`):
`NansenClient(api_key)` with `smart_money_netflows(chains=["solana"])`, `token_holders(mint)`,
`token_flows(mint)`, `screener(filters)`; 24h file cache so a cycle costs pennies at $0.01/query;
missing key → neutral defaults (demo-safe, same fallback pattern as `regime_hmm.py` without hmmlearn).
Wire order: netflows → `onchain_flow_signal` → ensemble; historical → validation OOS; alerts → `alerting.py`.
`.env` addition: `NANSEN_API_KEY=` (or x402 wallet path). Never commit the key (gitleaks CI).

---

## 11. What to feed me next (equation refs — non-blocking)

Drop into `docs/EQUATIONS.md`: (a) BSM variant (American? discrete divs?), (b) HMM priors/windows,
(c) structured payoff beyond 90/10. Each fills ONE function (§3.8). Build proceeds without them.

*End — next actions: T6 verify (`anchor build`), T9 write `dbc_config.py`, T10 devnet pool, T11 IDL sync.*
