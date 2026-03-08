CREATE_TABLES = [
"""
CREATE TABLE IF NOT EXISTS group_settings (
  group_id INTEGER PRIMARY KEY,
  token_mint TEXT NOT NULL,
  token_name TEXT,
  min_buy_sol REAL NOT NULL DEFAULT 0,
  emoji TEXT NOT NULL DEFAULT '🟢',
  telegram_link TEXT,
  media_file_id TEXT,
  show_media INTEGER NOT NULL DEFAULT 1,
  show_mcap INTEGER NOT NULL DEFAULT 1,
  show_price INTEGER NOT NULL DEFAULT 1,
  show_dex INTEGER NOT NULL DEFAULT 1,
  is_active INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS tracked_tokens (
  mint TEXT PRIMARY KEY,
  token_name TEXT,
  telegram_link TEXT,
  post_mode TEXT NOT NULL DEFAULT 'channel',
  is_active INTEGER NOT NULL DEFAULT 1,
  force_trending INTEGER NOT NULL DEFAULT 0,
  force_leaderboard INTEGER NOT NULL DEFAULT 0,
  manual_rank INTEGER,
  manual_boost REAL NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS ads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by INTEGER NOT NULL,
  token_mint TEXT,
  text TEXT NOT NULL,
  link TEXT,
  scope TEXT NOT NULL DEFAULT 'global',
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  tx_sig TEXT NOT NULL UNIQUE,
  amount_sol REAL NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS state_kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS buys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mint TEXT NOT NULL,
  usd REAL NOT NULL,
  ts INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS price_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mint TEXT NOT NULL,
  price_usd REAL NOT NULL,
  mcap_usd REAL,
  ts INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS trending_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  token_mint TEXT NOT NULL,
  link TEXT,
  emoji TEXT,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  tx_sig TEXT NOT NULL UNIQUE,
  amount_sol REAL NOT NULL
);
""",
]
