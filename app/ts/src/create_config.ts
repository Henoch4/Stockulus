import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import {
  PartnerService,
  ActivationType,
  BaseFeeMode,
  buildCurveWithCustomSqrtPrices,
  CollectFeeMode,
  createSqrtPrices,
  MigrationOption,
  MigrationFeeOption,
  TokenDecimal,
  TokenType,
  TokenAuthorityOption,
} from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const partnerService = new PartnerService(connection, "confirmed");

// Quote mint + decimals are env-driven: devnet has no Circle USDC, so we use
// wSOL (9dp) on devnet; mainnet uses USDC (6dp). See .env QUOTE_MINT/QUOTE_DECIMALS.
const QUOTE_MINT = new PublicKey(
  process.env.QUOTE_MINT || "So11111111111111111111111111111111111111112"
);
const QUOTE_DECIMALS =
  process.env.QUOTE_DECIMALS === "SIX" ? TokenDecimal.SIX : TokenDecimal.NINE;
// Base decimals + token program env-driven: xStocks are Token-2022/8dp
// (mainnet AAPLx: TokenzQ..., scaled-UI + transferHook + pausable).
// Devnet mock mirrors decimals; transferHook path is a mainnet step (Phase C).
const BASE_DECIMALS =
  process.env.BASE_DECIMALS === "SIX"
    ? TokenDecimal.SIX
    : process.env.BASE_DECIMALS === "NINE"
      ? TokenDecimal.NINE
      : TokenDecimal.EIGHT;
const TOKEN_TYPE =
  process.env.TOKEN_TYPE === "SPL" ? TokenType.SPLToken : TokenType.Token2022;

// Usage: node dist/create_config.js <regime_scale>
const regimeScale = parseFloat(process.argv[2] || "1.0");

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

function stockCurve(regimeScale: number) {
  const exponential = regimeScale <= 0.9;
  const sqrtPrices = createSqrtPrices(
    [0.000001, 0.0000012, 0.000002, 0.00001],
    BASE_DECIMALS,
    QUOTE_DECIMALS
  );
  return buildCurveWithCustomSqrtPrices({
    token: {
      tokenType: TOKEN_TYPE,
      tokenBaseDecimal: BASE_DECIMALS,
      tokenQuoteDecimal: QUOTE_DECIMALS,
      tokenAuthorityOption: TokenAuthorityOption.PartnerUpdateAuthority,
      totalTokenSupply: 1_000_000_000,
      leftover: 1000,
    },
    fee: {
      baseFeeParams: {
        baseFeeMode: exponential ? BaseFeeMode.FeeSchedulerExponential : BaseFeeMode.FeeSchedulerLinear,
        feeSchedulerParam: {
          startingFeeBps: exponential ? 900 : 120,
          endingFeeBps: 100,
          numberOfPeriod: 60,
          totalDuration: 3600,
        },
      },
      dynamicFeeEnabled: true,
      collectFeeMode: CollectFeeMode.QuoteToken,
      creatorTradingFeePercentage: 50,
      poolCreationFee: 0,
      enableFirstSwapWithMinFee: false,
    },
    migration: {
      migrationOption: MigrationOption.MET_DAMM_V2,
      migrationFeeOption: MigrationFeeOption.Customizable,
      migrationFee: { feePercentage: 10, creatorFeePercentage: 50 },
      migratedPoolFee: { collectFeeMode: 0, dynamicFee: 1, poolFeeBps: 100, baseFeeMode: 0 },
    },
    liquidityDistribution: {
      partnerLiquidityPercentage: 0,
      partnerPermanentLockedLiquidityPercentage: 100,
      creatorLiquidityPercentage: 0,
      creatorPermanentLockedLiquidityPercentage: 0,
    },
    lockedVesting: {
      totalLockedVestingAmount: 0,
      numberOfVestingPeriod: 0,
      cliffUnlockAmount: 0,
      totalVestingDuration: 0,
      cliffDurationFromMigrationTime: 0,
    },
    activationType: ActivationType.Timestamp,
    sqrtPrices,
    liquidityWeights: [2, 1, 1],
  });
}

async function main() {
  try {
    const partner = loadKeypair();
    const config = Keypair.generate();

    const curveConfig = stockCurve(regimeScale);
    const quoteMint = QUOTE_MINT; // env-driven (wSOL devnet / USDC mainnet)

    const tx = await partnerService.createConfig({
      config: config.publicKey,
      feeClaimer: partner.publicKey,
      leftoverReceiver: partner.publicKey,
      payer: partner.publicKey,
      quoteMint,
      ...curveConfig,
    });

    tx.feePayer = partner.publicKey;
    tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
    tx.sign(partner, config);
    const txSig = await connection.sendRawTransaction(tx.serialize(), {
      skipPreflight: false,
      preflightCommitment: "confirmed",
    });
    await connection.confirmTransaction(txSig, "confirmed");

    console.log(JSON.stringify({
      config: config.publicKey.toString(),
      tx: txSig,
      regimeScale,
    }, null, 2));
  } catch (e: any) {
    console.error("Error:", e?.message || e);
    process.exit(1);
  }
}

main();