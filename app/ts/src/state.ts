import { Connection, PublicKey } from "@solana/web3.js";
import { StateService } from "@meteora-ag/dynamic-bonding-curve-sdk";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const stateService = new StateService(connection, "confirmed");

// Usage: node dist/state.js <pool_pubkey>
const poolPubkey = process.argv[2];
if (!poolPubkey) {
  console.error("Usage: node dist/state.js <pool_pubkey>");
  process.exit(1);
}

async function main() {
  try {
    const pool = new PublicKey(poolPubkey);
    const poolAccount = await stateService.getPool(pool);
    if (!poolAccount) {
      console.error("Pool not found or account not initialized");
      process.exit(1);
    }
    const poolState = poolAccount.poolState;
    const configState = await stateService.getPoolConfig(poolState.config);

    console.log(JSON.stringify({
      pool: poolPubkey,
      config: poolState.config.toString(),
      baseMint: poolState.baseMint.toString(),
      quoteMint: configState ? configState.quoteMint.toString() : "unknown",
      baseVault: poolState.baseVault.toString(),
      quoteVault: poolState.quoteVault.toString(),
      baseReserve: poolState.baseReserve.toString(),
      quoteReserve: poolState.quoteReserve.toString(),
      sqrtPrice: poolState.sqrtPrice.toString(),
      migrationProgress: poolState.migrationProgress.toString(),
      isMigrated: poolState.isMigrated,
      activationPoint: poolState.activationPoint.toString(),
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();