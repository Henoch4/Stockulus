import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { CreatorService, deriveDbcPoolAddress } from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";

// Env-driven quote mint (wSOL devnet / USDC mainnet) — must match the config.
const QUOTE_MINT = new PublicKey(
  process.env.QUOTE_MINT || "So11111111111111111111111111111111111111112"
);

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const creatorService = new CreatorService(connection, "confirmed");

// Usage: node dist/create_pool.js <base_mint> <config_pubkey> <name> <symbol> <uri> [base_mint_keypair_path]
// The base mint MUST sign (DBC program constraint — verified on-chain). For fresh
// demo mints pass the file saved by create_mint.js. Env BASE_MINT_KEYPAIR also honored.
const [,, baseMintStr, configPubkeyStr, name, symbol, uri, baseMintKpArg] = process.argv;
if (!baseMintStr || !configPubkeyStr || !name || !symbol || !uri) {
  console.error("Usage: node dist/create_pool.js <base_mint> <config_pubkey> <name> <symbol> <uri>");
  process.exit(1);
}

  function loadBaseMintKeypair(): Keypair | null {
    const p = baseMintKpArg || process.env.BASE_MINT_KEYPAIR;
    if (!p) return null;
    const raw = fs.readFileSync(p, "utf8").trim();
    return Keypair.fromSecretKey(
      Buffer.from(raw.startsWith("[") ? JSON.parse(raw) : Buffer.from(raw, "hex"))
    );
  }

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
    const creator = loadKeypair();
    const baseMint = new PublicKey(baseMintStr);
    const config = new PublicKey(configPubkeyStr);

    const tx = await creatorService.createPool({
      baseMint,
      config,
      name,
      symbol,
      uri,
      payer: creator.publicKey,
      poolCreator: creator.publicKey,
    });

    tx.feePayer = creator.publicKey;
    tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
    // Base mint MUST sign (DBC program constraint). Fresh demo mints pass their
    // keypair file (arg 6 / BASE_MINT_KEYPAIR); without it the tx fails closed.
    const baseMintKp = loadBaseMintKeypair();
    if (baseMintKp && !baseMintKp.publicKey.equals(baseMint)) {
      console.error(`Base mint keypair mismatch: file=${baseMintKp.publicKey} arg=${baseMint}`);
      process.exit(1);
    }
    tx.sign(...(baseMintKp ? [creator, baseMintKp] : [creator]));
    const txSig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction(txSig, "confirmed");

    const pool = deriveDbcPoolAddress(
      QUOTE_MINT,
      baseMint,
      config
    );

    console.log(JSON.stringify({
      pool: pool.toString(),
      tx: txSig,
      baseMint: baseMintStr,
      config: configPubkeyStr,
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();