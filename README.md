# PumpTools BuyBot (Solana + Pump.fun)

A Telegram BuyBot focused on **Solana** (including Pump.fun tokens) with:
- **Group setup wizard** (no commands needed for group admins)
- **Min-buy filter** (admins type any SOL amount)
- **SOL → USD** on the "Spent" line
- **Ads under buys** with **on-chain payment verification**
- **Owner controls**: add tokens to track and post buys directly to a channel

> Trending/leaderboard is intentionally NOT included (separate bot).

## What you need
1. A Telegram bot token from @BotFather
2. A Solana RPC endpoint (WebSocket + HTTPS). Recommended: Helius.
3. (Recommended) `HELIUS_API_KEY` for reliable buy detection via Helius Enhanced Transactions API.
   - Without it, the bot still runs, but buy detection falls back to basic polling and may miss swaps.

## Deploy (Railway)
1. Push this repo to GitHub
2. Create a new Railway project from the repo
3. Add variables (see `.env.example`)
4. Deploy

## Group usage
- Add the bot to your group
- Make it **Admin** (send messages + embed links)
- Tap **Configure BuyBot**
- Follow the wizard:
  - Token mint (CA)
  - Minimum buy in SOL
  - Emoji
  - Telegram link
  - Optional media (photo)
  - Activate

## Ads
In any group where the bot is active, run:
- `/ads` → choose duration → send ad text + tx signature
The bot verifies the payment to `PAYMENT_WALLET` and then shows your ad under buys while active.

## Owner commands
- `/addtoken <MINT>` → start tracking token globally and post buys to `POST_CHANNEL`
- `/removetoken <MINT>`
- `/setad <text>` → set global fallback ad text (owner only)
- `/status`

## Notes on "buy detection"
This project detects buys by polling **parsed transactions** for the token mint address using:
- Helius Enhanced Transactions API (best)
It identifies swaps where:
- Buyer spent SOL (or wSOL) and received the target token.

You can adjust polling and thresholds in env vars.

