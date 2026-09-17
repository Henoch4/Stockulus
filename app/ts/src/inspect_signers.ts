import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { CreatorService } from "@meteora-ag/dynamic-bonding-curve-sdk";
import * as fs from "fs";

const connection = new Connection(process.env.RPC_URL || "https://api.devnet.solana.com", "confirmed");
const creatorService = new CreatorService(connection, "confirmed");

const [,, baseMintStr, configPubkeyStr] = process.argv;

async function main() {
  const rawKey = fs.readFileSync(process.env.KEYPAIR_PATH!, "utf8").trim();
  const creator = Keypair.fromSecretKey(
    Buffer.from(rawKey.startsWith("[") ? JSON.parse(rawKey) : Buffer.from(rawKey, "hex"))
  );
  const tx = await creatorService.createPool({
    baseMint: new PublicKey(baseMintStr),
    config: new PublicKey(configPubkeyStr),
    name: "x",
    symbol: "x",
    uri: "https://x",
    payer: creator.publicKey,
    poolCreator: creator.publicKey,
  });
  tx.feePayer = creator.publicKey;
  tx.recentBlockhash = (await connection.getLatestBlockhash("confirmed")).blockhash;
  const msg = tx.compileMessage();
  const keys = msg.accountKeys;
  console.log("numRequiredSignatures:", msg.header.numRequiredSignatures);
  keys.forEach((k, i) => {
    const isSigner = i < msg.header.numRequiredSignatures;
    console.log(isSigner ? "SIGNER" : "      ", k.toString());
  });
}

main();
