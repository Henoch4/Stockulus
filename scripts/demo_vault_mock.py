"""Live vault loop on devnet with mock USDC (classic SPL, 6dp).

$5 cap: deposits exactly 5.0 mock-USDC, withdraws everything at the end.
Proves: initialize → deposit → attest (+1%) → timelock REJECT → delta-cap
REJECT → withdraw. Both guardrails proven by expected-failure txs.

Requires: upgraded TradingVault (init vault_token_account + timelock check).
See .github/workflows/upgrade-vault-devnet.yml.

Usage (repo root):  python scripts/demo_vault_mock.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.vault_client_sol import SolanaVaultClient, derive_vault_pda
from solders.keypair import Keypair
from solders.pubkey import Pubkey

DEPOSIT = 5_000_000  # 5.0 mock-USDC (6dp) — hard cap for this demo
MIN_DEPOSIT = 1_000_000  # 1.0
MAX_TVL = 100_000_000  # 100.0 (matches $100 risk config)
TIMELOCK_S = 5  # demo vault: seconds (mainnet would use hours)
DELTA_BPS = 500  # 5% max NAV move per attestation

SOLSCAN = "https://solscan.io/tx/{}?cluster=devnet"


def load_keypair(path: str) -> Keypair:
    raw = Path(path).read_text(encoding="utf-8").strip()
    try:
        secret = bytes(json.loads(raw))
    except ValueError:
        secret = bytes.fromhex(raw)
    return Keypair.from_bytes(secret)


def run_mock_setup(rpc_url: str, keypair_path: str, vault_program_id: str) -> dict:
    ts_dir = Path(__file__).resolve().parent.parent / "app" / "ts"
    env = {
        **os.environ,
        "RPC_URL": rpc_url,
        "KEYPAIR_PATH": keypair_path,
        "VAULT_PROGRAM_ID": vault_program_id,
    }
    cmd = ["node", str(ts_dir / "dist" / "create_mock_usdc.js")]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"create_mock_usdc failed: {r.stderr[-2000:]}")
    return json.loads(r.stdout.strip())


async def expect_anchor_error(coro, match: list[str], label: str):
    """Run coro expecting an Anchor error containing one of match."""
    try:
        tx = await coro
    except Exception as e:  # noqa: BLE001 — expected-failure probe
        msg = str(e)
        if any(m in msg for m in match):
            print(f"  [EXPECTED FAIL] {label}: guardrail held")
            return None
        raise RuntimeError(f"{label}: wrong error: {msg[-500:]}")
    raise RuntimeError(f"{label}: tx unexpectedly SUCCEEDED: {tx}")


async def main() -> None:
    rpc_url = os.getenv("RPC_URL", "https://api.devnet.solana.com")
    vault_program_id = os.getenv("VAULT_PROGRAM_ID")
    keypair_path = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    if not vault_program_id:
        print("ERROR: VAULT_PROGRAM_ID not set in .env")
        return

    kp = load_keypair(keypair_path)
    txs: dict[str, str] = {}

    print("== 1/6 mock USDC setup ==")
    # The vault binds to ONE mint forever (vault.mint is immutable) — reuse
    # the recorded demo mint across runs instead of minting a new one.
    mock_path = Path(__file__).resolve().parent.parent / "config" / "mock_usdc.json"
    if mock_path.exists():
        setup = json.loads(mock_path.read_text(encoding="utf-8"))
        print(f"  reusing recorded demo mint {setup['mint']}")
    else:
        setup = run_mock_setup(rpc_url, keypair_path, vault_program_id)
        mock_path.write_text(json.dumps(setup, indent=2), encoding="utf-8")
    mint = Pubkey.from_string(setup["mint"])
    ata = Pubkey.from_string(setup["agentAta"])
    print(f"  mint={mint} ata={ata} setup_tx={setup['mintTx']}")
    txs["mock_mint"] = setup["mintTx"]

    client = SolanaVaultClient(rpc_url, vault_program_id, kp)
    await client.connect()

    print("== 2/6 initialize (idempotent) ==")
    try:
        txs["initialize"] = await client.initialize(
            mint, MIN_DEPOSIT, MAX_TVL, TIMELOCK_S, DELTA_BPS
        )
        print(f"  initialized: {txs['initialize']}")
    except Exception as e:  # noqa: BLE001 — re-runs hit 'already in use'
        if "already in use" in str(e) or "0x0" in str(e):
            print("  vault already initialized — continuing")
        else:
            raise

    print("== 3/6 deposit 5.0 mock-USDC ==")
    v0 = await client.read_vault(kp.pubkey())
    exp_shares = (
        DEPOSIT if v0.total_shares == 0
        else DEPOSIT * v0.total_shares // v0.total_assets
    )
    txs["deposit"] = await client.deposit(mint, ata, DEPOSIT)
    v = await client.read_vault(kp.pubkey())
    assert v.total_assets == v0.total_assets + DEPOSIT, (v0.total_assets, v.total_assets)
    assert v.total_shares == v0.total_shares + exp_shares, (v0.total_shares, v.total_shares)
    print(f"  assets={v.total_assets} shares={v.total_shares} tx={txs['deposit']}")

    print("== 4/6 top-up 0.05 yield + attest (within 500bps cap) ==")
    import subprocess as _sp

    YIELD = 50_000  # 0.05 mock-USDC of strategy yield (1% of first deposit)
    _ts_dir = Path(__file__).resolve().parent.parent / "app" / "ts"
    _env = {**_sp.os.environ, "RPC_URL": rpc_url, "KEYPAIR_PATH": keypair_path,
            "VAULT_PROGRAM_ID": vault_program_id}
    _cmd = ["node", str(_ts_dir / "dist" / "top_up_vault.js"), str(mint), str(YIELD)]
    _r = _sp.run(_cmd, capture_output=True, text=True, env=_env, timeout=120)
    if _r.returncode != 0:
        raise RuntimeError(f"top_up_vault failed: {_r.stderr[-2000:]}")
    topup = json.loads(_r.stdout.strip())
    print(f"  yield in: {topup['vaultBalance']} held, tx={topup['tx']}")
    txs["topup_yield"] = topup["tx"]
    # Attest to ACTUAL holdings (the top-up script reports the post-transfer
    # balance) — never to books+YIELD, which double-counts the top-up.
    drifted = int(topup["vaultBalance"])
    for attempt in range(3):
        try:
            txs["attest_ok"] = await client.attest_total_assets(drifted)
            break
        except Exception as e:  # noqa: BLE001 — re-run may hit leftover timelock
            if ("6006" in str(e) or "TooSoon" in str(e)) and attempt < 2:
                print("  timelock from earlier run — waiting it out")
                time.sleep(TIMELOCK_S + 1)
                continue
            raise
    print(f"  attested {drifted} tx={txs['attest_ok']}")

    print("== 5/6 guardrails (expected failures) ==")
    await expect_anchor_error(
        client.attest_total_assets(drifted),
        ["6006", "TooSoon", "too soon"],
        "timelock (5s) blocks immediate re-attest",
    )
    time.sleep(TIMELOCK_S + 1)
    v = await client.read_vault(kp.pubkey())
    await expect_anchor_error(
        client.attest_total_assets(v.total_assets * 150 // 100),
        ["6005", "DeltaTooLarge", "too large"],
        "delta cap (500bps) blocks +50% attestation",
    )

    print("== 6/6 withdraw all shares ==")
    v = await client.read_vault(kp.pubkey())
    txs["withdraw"] = await client.withdraw(mint, ata, v.total_shares)
    v = await client.read_vault(kp.pubkey())
    assert v.total_assets == 0, v.total_assets
    assert v.total_shares == 0, v.total_shares
    print(f"  assets={v.total_assets} shares={v.total_shares} tx={txs['withdraw']}")

    await client.close()
    txs = {k: str(s) for k, s in txs.items()}
    print(json.dumps({
        "mint": str(mint),
        "vault": str(derive_vault_pda(client.program_id, kp.pubkey())[0]),
        "txs": txs,
        "solscan": {k: SOLSCAN.format(s) for k, s in txs.items()},
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
