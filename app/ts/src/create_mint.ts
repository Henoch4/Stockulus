import { Keypair } from "@solana/web3.js";
import * as fs from "fs";

// Usage: node dist/create_mint.js <decimals> [name-hint] [out-path]
// Saves the mint keypair (REQUIRED later: DBC pool creation needs the base
// mint itself as a signer). Default out: ./mint-<hint>.json next to CWD.
// Creates a plain Token-2022 mint (no transfer hook) mirroring xStocks decimals.
// Devnet demo mint — NOT backed equity. Mainnet uses real xStocks mints
// (which carry transferHook/pausable extensions → transfer-hook DBC path, Phase C).

const decimals = parseInt(process.argv[2] || "8", 10);
const hint = process.argv[3] || "demo";
const outPath = process.argv[4] || `./mint-${hint}.json`;

function loadKeypair(): Keypair {
  const keypairPath = process.env.KEYPAIR_PATH;
  if (!keypairPath) {
    console.error("KEYPAIR_PATH not set");
    process.exit(1);
  }
  const rawKey = fs.readFileSync(keypairPath, "utf8").trim();
  // solana-keygen JSON array or raw hex — accept both.
  const secret = Buffer.from(rawKey.startsWith("[") ? JSON.parse(rawKey) : Buffer.from(rawKey, "hex"));
  return Keypair.fromSecretKey(secret);
}

async function main() {
  try {
    const mintKp = Keypair.generate();
    const mint = mintKp.publicKey;
    fs.writeFileSync(outPath, JSON.stringify(Array.from(mintKp.secretKey)));
    console.log(JSON.stringify({
      mint: mint.toString(),
      decimals,
      note: "UNINITIALIZED — DBC pool creation allocates+inits this mint (keypair signs as baseMint).",
      keypairPath: outPath,
    }, null, 2));
    console.error(`Mint keypair saved to ${outPath} — KEEP IT (pool creation needs its signature).`);
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();
