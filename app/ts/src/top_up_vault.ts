import { Connection, Keypair, PublicKey, Transaction } from "@solana/web3.js";
import {
  getOrCreateAssociatedTokenAccount,
  createTransferInstruction,
  TOKEN_PROGRAM_ID,
  getAccount,
} from "@solana/spl-token";
import * as fs from "fs";

// Usage: node dist/top_up_vault.js <mint> <amount_base_units>
// Simulates strategy yield: plain SPL transfer from the agent ATA straight
// into the vault's token PDA (no program call — the later attestation is
// what prices it into NAV). Prints JSON: { tx, vaultToken, vaultBalance }.
const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const VAULT_PROGRAM_ID = new PublicKey(
  process.env.VAULT_PROGRAM_ID || "Gd7Ciu6KgPwoajZZgAUNethJAFNe4s3nhJV64XNRz9aF"
);

function loadKeypair(): Keypair {
  const keypairPath = process.env.KEYPAIR_PATH;
  if (!keypairPath) {
    console.error("KEYPAIR_PATH not set");
    process.exit(1);
  }
  const rawKey = fs.readFileSync(keypairPath, "utf8").trim();
  const secret = Buffer.from(rawKey.startsWith("[") ? JSON.parse(rawKey) : Buffer.from(rawKey, "hex"));
  return Keypair.fromSecretKey(secret);
}

async function main() {
  try {
    const mint = new PublicKey(process.argv[2]);
    const amount = BigInt(process.argv[3]);
    if (!amount || amount <= 0n) {
      console.error("Usage: node dist/top_up_vault.js <mint> <amount_base_units>");
      process.exit(1);
    }
    const agent = loadKeypair();
    const [vaultPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault"), agent.publicKey.toBuffer()],
      VAULT_PROGRAM_ID
    );
    const [vaultTokenPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault_token"), vaultPda.toBuffer()],
      VAULT_PROGRAM_ID
    );
    const ata = await getOrCreateAssociatedTokenAccount(
      connection,
      agent,
      mint,
      agent.publicKey,
      false,
      "confirmed",
      { commitment: "confirmed" },
      TOKEN_PROGRAM_ID
    );
    const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash("confirmed");
    const tx = new Transaction({
      feePayer: agent.publicKey,
      blockhash,
      lastValidBlockHeight,
    }).add(
      createTransferInstruction(ata.address, vaultTokenPda, agent.publicKey, amount, [], TOKEN_PROGRAM_ID)
    );
    tx.sign(agent);
    const sig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction({ signature: sig, blockhash, lastValidBlockHeight }, "confirmed");
    const bal = await getAccount(connection, vaultTokenPda, "confirmed", TOKEN_PROGRAM_ID);
    console.log(JSON.stringify({
      tx: sig,
      vaultToken: vaultTokenPda.toString(),
      vaultBalance: bal.amount.toString(),
    }));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();
