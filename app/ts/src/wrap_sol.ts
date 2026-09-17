import { Connection, Keypair, PublicKey, SystemProgram, Transaction } from "@solana/web3.js";
import {
  getOrCreateAssociatedTokenAccount,
  createSyncNativeInstruction,
  NATIVE_MINT,
} from "@solana/spl-token";
import * as fs from "fs";

// Usage: node dist/wrap_sol.js <amount_sol>
// Wraps native SOL to wSOL ATA (creates ATA if missing). Prints wSOL balance.
const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");

const amountSol = parseFloat(process.argv[2] || "0");
if (!amountSol || amountSol <= 0) {
  console.error("Usage: node dist/wrap_sol.js <amount_sol>");
  process.exit(1);
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
    const owner = loadKeypair();
    const lamports = Math.floor(amountSol * 1e9);

    const ata = await getOrCreateAssociatedTokenAccount(
      connection,
      owner,
      NATIVE_MINT,
      owner.publicKey
    );

    const tx = new Transaction().add(
      SystemProgram.transfer({
        fromPubkey: owner.publicKey,
        toPubkey: ata.address,
        lamports,
      }),
      createSyncNativeInstruction(ata.address)
    );
    tx.feePayer = owner.publicKey;
    tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
    tx.sign(owner);
    const txSig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction(txSig, "confirmed");

    const bal = await connection.getTokenAccountBalance(ata.address);
    console.log(JSON.stringify({
      tx: txSig,
      wsolAta: ata.address.toString(),
      wsolBalance: bal.value.uiAmountString,
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();
