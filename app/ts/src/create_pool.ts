import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { CreatorService, deriveDbcPoolAddress } from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const creatorService = new CreatorService(connection, "confirmed");

// Usage: node dist/create_pool.js <base_mint> <config_pubkey> <name> <symbol> <uri>
const [,, baseMintStr, configPubkeyStr, name, symbol, uri] = process.argv;
if (!baseMintStr || !configPubkeyStr || !name || !symbol || !uri) {
  console.error("Usage: node dist/create_pool.js <base_mint> <config_pubkey> <name> <symbol> <uri>");
  process.exit(1);
}

function loadKeypair(): Keypair {
  const keypairPath = process.env.KEYPAIR_PATH;
  if (!keypairPath) {
    console.error("KEYPAIR_PATH not set");
    process.exit(1);
  }
  const secret = Buffer.from(fs.readFileSync(keypairPath, "utf8").trim(), "hex");
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

    tx.sign(creator);
    const txSig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction(txSig, "confirmed");

    const pool = deriveDbcPoolAddress(
      new PublicKey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"), // USDC
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