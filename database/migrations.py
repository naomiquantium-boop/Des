CREATE_TABLES = [
"""
CREATE TABLE IF NOT EXISTS group_settings (
  group_id INTEGER PRIMARY KEY,
  token_mint TEXT NOT NULL,
  min_buy_sol REAL NOT NULL,
  emoji TEXT NOT NULL,
  telegram_link TEXT,
  media_file_id TEXT,
  is_active INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS tracked_tokens (
  mint TEXT PRIMARY KEY,
  post_mode TEXT NOT NULL, -- 'channel' or 'none'
  telegram_link TEXT,
  emoji TEXT,
  created_at INTEGER NOT NULL
);
""",
"""
CREATE TABLE IF NOT EXISTS ads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by INTEGER NOT NULL,
  text TEXT NOT NULL,
  url TEXT,
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
"""

,
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
  ts INTEGER NOT NULL
);
"""

]
