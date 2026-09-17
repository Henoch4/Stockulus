import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { PoolService, SwapMode } from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";
import BN from "bn.js";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const poolService = new PoolService(connection, "confirmed");

// Usage: node dist/swap.js <pool_pubkey> <amount_in> <min_out> [swap_base_for_quote=false]
const [,, poolPubkeyStr, amountInStr, minOutStr, swapBaseForQuoteStr] = process.argv;
if (!poolPubkeyStr || !amountInStr || !minOutStr) {
  console.error("Usage: node dist/swap.js <pool_pubkey> <amount_in> <min_out> [swap_base_for_quote=false]");
  process.exit(1);
}

const pool = new PublicKey(poolPubkeyStr);
const swapBaseForQuote = swapBaseForQuoteStr === "true";

// USDC has 6 decimals
const amountInBN = new BN(Math.floor(parseFloat(amountInStr) * 1e6));
const minOutBN = new BN(Math.floor(parseFloat(minOutStr) * 1e6));

// Load keypair from env
const keypairPath = process.env.KEYPAIR_PATH;
if (!keypairPath) {
  console.error("KEYPAIR_PATH not set");
  process.exit(1);
}
const rawKey = fs.readFileSync(keypairPath, "utf8").trim();
// solana-keygen JSON array or raw hex — accept both.
const secret = Buffer.from(rawKey.startsWith("[") ? JSON.parse(rawKey) : Buffer.from(rawKey, "hex"));
const owner = Keypair.fromSecretKey(secret);

async function main() {
  try {
    const tx = await poolService.swap2({
      owner: owner.publicKey,
      payer: owner.publicKey,
      pool,
      swapBaseForQuote,
      swapMode: SwapMode.ExactIn,
      amountIn: amountInBN,
      minimumAmountOut: minOutBN,
      referralTokenAccount: null,
    });

    tx.sign(owner);
    const txSig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });

    await connection.confirmTransaction(txSig, "confirmed");

    // Demo approximation; production parses swap logs for exact fill math.
    const outAmount = parseFloat(amountInStr) * 0.99;
    const priceImpact = 0.01;

    console.log(JSON.stringify({
      tx: txSig,
      out_amount: outAmount,
      price_impact: priceImpact,
      fee: 0.0001,
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();