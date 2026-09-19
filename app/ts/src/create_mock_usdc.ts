import { Connection, Keypair, PublicKey } from "@solana/web3.js";
import {
  createMint,
  getOrCreateAssociatedTokenAccount,
  mintTo,
  setAuthority,
  AuthorityType,
  TOKEN_PROGRAM_ID,
} from "@solana/spl-token";
import * as fs from "fs";

// Usage: node dist/create_mock_usdc.js
// Creates a classic-SPL mock USDC mint (6dp), mints 1000 to the agent ATA,
// then hands mint authority to the vault PDA (deposit mints shares via CPI).
// Prints JSON: { mint, agentAta, vaultPda, txs }.
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
    const agent = loadKeypair();
    const [vaultPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("vault"), agent.publicKey.toBuffer()],
      VAULT_PROGRAM_ID
    );

    const mint = await createMint(
      connection,
      agent,
      agent.publicKey,
      null,
      6,
      undefined,
      { commitment: "confirmed" },
      TOKEN_PROGRAM_ID
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

    const mintSig = await mintTo(
      connection,
      agent,
      mint,
      ata.address,
      agent.publicKey,
      1000 * 1e6,
      [],
      { commitment: "confirmed" },
      TOKEN_PROGRAM_ID
    );

    await setAuthority(
      connection,
      agent,
      mint,
      agent.publicKey,
      AuthorityType.MintTokens,
      vaultPda,
      [],
      { commitment: "confirmed" },
      TOKEN_PROGRAM_ID
    );

    console.log(JSON.stringify({
      mint: mint.toString(),
      agentAta: ata.address.toString(),
      vaultPda: vaultPda.toString(),
      mintTx: mintSig,
    }));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();
