"""import_phantom_key.py — import a Phantom-exported key into solana-keygen JSON.

HUMAN: python scripts/import_phantom_key.py
  1. Paste the base58 secret when prompted (getpass — never echoed, never logged).
  2. Script writes ./agent_keypair.json (solana-keygen array format, gitignored).
  3. Script prints the derived pubkey — CONFIRM it matches your funded address
     before doing anything else.

Needs: pip install -r app/agent/requirements.txt  (uses solders for pubkey check)
Stdlib-only base58 decode, so the import itself has zero dependencies.
"""
from __future__ import annotations

import getpass
import json
import os
import sys

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s.strip():
        n = n * 58 + ALPHABET.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s.strip()) - len(s.strip().lstrip("1"))
    return b"\x00" * pad + raw


def main() -> int:
    out = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    if os.path.exists(out):
        print(f"REFUSING: {out} already exists — delete it explicitly if you mean to replace it.")
        return 1
    if "--from-file" in sys.argv:
        idx = sys.argv.index("--from-file")
        if idx + 1 >= len(sys.argv):
            print("ERROR: --from-file needs a path.")
            return 1
        try:
            with open(sys.argv[idx + 1], "r", encoding="utf-8") as f:
                secret_b58 = f.read()
        except OSError as e:
            print(f"ERROR: cannot read file: {e}")
            return 1
    else:
        secret_b58 = getpass.getpass("Paste private key (base58, invisible): ")
    # Mnemonic detection FIRST (on raw input): 12/24 plain-English words is a
    # RECOVERY PHRASE, not a key.
    if len(secret_b58.strip().split()) in (12, 15, 18, 21, 24):
        print("ERROR: that looks like a RECOVERY PHRASE (12/24 words), not a private key.")
        print("  Solflare: wallet → Settings → Export Private Key → copy the long")
        print("  single-line base58 string (starts with a letter/number, no spaces).")
        print("  Tip: paste into Notepad first, then: python scripts/import_phantom_key.py --from-file secret.txt")
        return 1
    # Normalize: cmd paste can inject spaces/line-breaks mid-string — drop all whitespace.
    secret_b58 = "".join(secret_b58.split())
    if not secret_b58:
        print("ERROR: empty input — the terminal ate your paste.")
        print("  Fix: paste the key into Notepad, save as secret.txt in this folder, then run:")
        print("    python scripts/import_phantom_key.py --from-file secret.txt")
        return 1
    try:
        secret = b58decode(secret_b58)
    except ValueError:
        print("ERROR: not valid base58 (allowed: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz, no 0/O/I/l).")
        print("  Re-copy the key as ONE line with no spaces and retry.")
        return 1
    finally:
        del secret_b58
    if len(secret) not in (32, 64):
        print(f"ERROR: decoded to {len(secret)} bytes, expected 32 (seed) or 64 (full secret).")
        return 1
    if len(secret) == 32:  # seed-only export → expand via solders
        try:
            from solders.keypair import Keypair
            secret = bytes(Keypair.from_seed(secret))
        except ImportError:
            print("ERROR: 32-byte seed needs solders: pip install -r app/agent/requirements.txt")
            return 1
    with open(out, "w", encoding="utf-8") as f:
        json.dump(list(secret), f)
    # File mode hygiene: if the key came from a temp file, delete it.
    src_file = sys.argv[sys.argv.index("--from-file") + 1] if "--from-file" in sys.argv else None
    if src_file and os.path.exists(src_file):
        try:
            os.remove(src_file)
            print(f"Deleted temp source file {src_file}")
        except OSError:
            print(f"WARNING: could not delete {src_file} — delete it manually NOW.")
    try:
        from solders.keypair import Keypair
        pubkey = str(Keypair.from_bytes(secret).pubkey())
    except ImportError:
        pubkey = "(solders not installed — install requirements to verify pubkey)"
    print(f"Wrote {out}")
    print(f"Derived pubkey: {pubkey}")
    print("CONFIRM this matches your funded address. If not, delete the file and retry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
