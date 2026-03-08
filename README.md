# Pumptools Telegram Buy Bot

Railway-ready Solana + Pump.fun Telegram buy bot with:
- group buy posts
- trending channel buy posts
- trending leaderboard footer: `To trend add @Pump_ToolsBot in your group`
- `🤍 Listing | 📈 Chart` row in buy posts
- default ad text: `Promote here with Pumptools Ads`
- owner-only force add / force trending / force leaderboard controls
- private main menu buttons similar to the Maziton flow

## Deploy on Railway
1. Upload this repo to GitHub.
2. Create a Railway project from the repo.
3. Add the variables from `.env.example`.
4. Deploy.

## Important
- Make the bot admin in groups/channels where it should post.
- For reliable buy detection, set `HELIUS_API_KEY` and use a Helius RPC URL.
- The bot uses SQLite by default so it runs easily on Railway volumes.

## Owner commands
- `/forceadd <mint> | <telegram link optional>`
- `/forcetrending <mint>`
- `/forceleaderboard <mint>`
- `/setglobalad <text>`
- `/status`

## Notes
This is a deployable starter focused on your requested style and flows. You can extend the UI pages, multilingual copy, and scoring rules further.
