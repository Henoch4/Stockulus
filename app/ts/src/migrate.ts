import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { MigrationService } from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const migrationService = new MigrationService(connection, "confirmed");

// Usage: node dist/migrate.js <pool_pubkey> <damm_v2_config>
const [,, poolPubkeyStr, dammConfigStr] = process.argv;
if (!poolPubkeyStr || !dammConfigStr) {
  console.error("Usage: node dist/migrate.js <pool_pubkey> <damm_v2_config>");
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
    const payer = loadKeypair();
    const pool = new PublicKey(poolPubkeyStr);
    const dammConfig = new PublicKey(dammConfigStr);

    const { transaction } = await migrationService.migrateToDammV2({
      payer: payer.publicKey,
      pool,
      dammConfig,
    });

    transaction.sign(payer);
    const txSig = await connection.sendRawTransaction(transaction.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction(txSig, "confirmed");

    console.log(JSON.stringify({
      tx: txSig,
      pool: poolPubkeyStr,
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();