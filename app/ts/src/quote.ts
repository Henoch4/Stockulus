import { Connection, PublicKey } from "@solana/web3.js";
import { StateService, PoolService, ActivationType, SwapMode } from "@meteora-ag/dynamic-bonding-curve-sdk";
import BN from "bn.js";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const stateService = new StateService(connection, "confirmed");
const poolService = new PoolService(connection, "confirmed");

// Usage: node dist/quote.js <pool_pubkey> <amount_in> [swap_base_for_quote=false] [slippage_bps=100]
const [,, poolPubkey, amountInStr, swapBaseForQuoteStr, slippageBpsStr] = process.argv;
if (!poolPubkey || !amountInStr) {
  console.error("Usage: node dist/quote.js <pool_pubkey> <amount_in> [swap_base_for_quote=false] [slippage_bps=100]");
  process.exit(1);
}

const amountIn = new BN(Math.floor(parseFloat(amountInStr) * 1e6)); // USDC 6dp
const swapBaseForQuote = swapBaseForQuoteStr === "true";
const slippageBps = parseInt(slippageBpsStr || "100");

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
    if (!configState) {
      console.error("Pool config not found");
      process.exit(1);
    }

    const currentPoint = configState.activationType === ActivationType.Slot
      ? new BN(await connection.getSlot())
      : new BN(Math.floor(Date.now() / 1000));

    const quote = poolService.swapQuote2({
      virtualPool: poolAccount,
      config: configState,
      swapBaseForQuote,
      swapMode: SwapMode.ExactIn,
      amountIn,
      slippageBps,
      hasReferral: false,
      eligibleForFirstSwapWithMinFee: false,
      currentPoint,
    });

    const tradingFee = (quote.tradingFee || 0).toString();
    const protocolFee = (quote.protocolFee || 0).toString();
    const referralFee = (quote.referralFee || 0).toString();

    console.log(JSON.stringify({
      out_amount: (quote.outputAmount || 0).toString(),
      minimum_amount_out: (quote.minimumAmountOut || quote.outputAmount || 0).toString(),
      trading_fee: tradingFee,
      protocol_fee: protocolFee,
      referral_fee: referralFee,
      total_fee: new BN(tradingFee).add(new BN(protocolFee)).add(new BN(referralFee)).toString(),
      next_sqrt_price: (quote.nextSqrtPrice || "0").toString(),
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();