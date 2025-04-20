CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS afk (
  left_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  status TEXT NOT NULL DEFAULT 'AFK',
  user_id BIGINT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS aliases (
  guild_id BIGINT NOT NULL,
  name TEXT NOT NULL,
  invoke TEXT NOT NULL,
  command TEXT NOT NULL,
  PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS antinuke (
  guild_id BIGINT UNIQUE NOT NULL,
  whitelist BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  trusted_admins BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  "bot" BOOLEAN NOT NULL DEFAULT FALSE,
  "ban" JSONB,
  "kick" JSONB,
  "role" JSONB,
  "channel" JSONB,
  "webhook" JSONB,
  "emoji" JSONB
);

CREATE TABLE IF NOT EXISTS thread (
  guild_id BIGINT NOT NULL,
  thread_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, thread_id)
);

CREATE TABLE IF NOT EXISTS roleplay (
    user_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    category TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, target_id, category)
);

CREATE TABLE IF NOT EXISTS antiraid (
  guild_id BIGINT NOT NULL,
  locked BOOLEAN NOT NULL DEFAULT FALSE,
  joins JSONB,
  mentions JSONB,
  avatar JSONB,
  browser JSONB,
  PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS auto_role (
  guild_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  action TEXT NOT NULL,
  delay INTEGER,
  PRIMARY KEY (guild_id, role_id, action)
);

CREATE TABLE IF NOT EXISTS blacklist (
  information TEXT,
  user_id BIGINT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS boost_message (
  channel_id BIGINT NOT NULL,
  delete_after INTEGER,
  guild_id BIGINT NOT NULL,
  template TEXT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS booster_role (
  guild_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS boosters_lost (
  ended_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  guild_id BIGINT NOT NULL,
  lasted_for INTERVAL NOT NULL,
  user_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS birthdays (
  birthday TIMESTAMP NOT NULL,
  user_id BIGINT UNIQUE NOT NULL
);

CREATE SCHEMA IF NOT EXISTS disboard;

CREATE TABLE IF NOT EXISTS disboard.bump (
  guild_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  bumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS disboard.config (
  guild_id BIGINT UNIQUE NOT NULL,
  status BOOLEAN NOT NULL DEFAULT TRUE,
  channel_id BIGINT,
  last_channel_id BIGINT,
  last_user_id BIGINT,
  message TEXT,
  thank_message TEXT,
  next_bump TIMESTAMP WITH TIME ZONE
);

CREATE SCHEMA IF NOT EXISTS feeds;

CREATE TABLE IF NOT EXISTS feeds.instagram (
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    instagram_id BIGINT NOT NULL,
    instagram_name TEXT NOT NULL,
    template TEXT,
    PRIMARY KEY (guild_id, instagram_id)
);

CREATE TABLE IF NOT EXISTS feeds.pinterest (
    board TEXT,
    board_id TEXT,
    channel_id BIGINT NOT NULL,
    embeds BOOLEAN NOT NULL DEFAULT TRUE,
    guild_id BIGINT NOT NULL,
    only_new BOOLEAN NOT NULL DEFAULT FALSE,
    pinterest_id TEXT NOT NULL,
    pinterest_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, pinterest_id)
);

CREATE TABLE IF NOT EXISTS feeds.reddit (
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    subreddit_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, subreddit_name)
);

CREATE TABLE IF NOT EXISTS feeds.tiktok (
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    template TEXT,
    tiktok_id BIGINT NOT NULL,
    tiktok_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, tiktok_id)
);

CREATE TABLE IF NOT EXISTS feeds.twitter (
    channel_id BIGINT NOT NULL,
    color TEXT,
    guild_id BIGINT NOT NULL,
    template TEXT,
    twitter_id BIGINT NOT NULL,
    twitter_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, twitter_id)
);

CREATE TABLE IF NOT EXISTS feeds.youtube (
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    shorts BOOLEAN NOT NULL DEFAULT FALSE,
    template TEXT,
    youtube_id TEXT NOT NULL,
    youtube_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, youtube_id)
);

CREATE SCHEMA IF NOT EXISTS fortnite;

CREATE TABLE IF NOT EXISTS fortnite.reminder (
    user_id BIGINT NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    item_type TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS fortnite.rotation (
    guild_id BIGINT UNIQUE NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT
);

CREATE TABLE IF NOT EXISTS gallery (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS goodbye_message (
  channel_id BIGINT NOT NULL,
  delete_after INTEGER,
  guild_id BIGINT NOT NULL,
  template TEXT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS logging (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  events INTEGER NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE SCHEMA IF NOT EXISTS lastfm;

CREATE TABLE IF NOT EXISTS lastfm.config (
    user_id BIGINT UNIQUE NOT NULL,
    username CITEXT NOT NULL,
    color BIGINT,
    command TEXT,
    reactions TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    embed_mode TEXT NOT NULL DEFAULT 'default',
    last_indexed TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lastfm.artists (
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    artist CITEXT NOT NULL,
    plays BIGINT NOT NULL,
    PRIMARY KEY (user_id, artist),
    FOREIGN KEY (user_id) REFERENCES lastfm.config (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lastfm.albums (
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    artist CITEXT NOT NULL,
    album CITEXT NOT NULL,
    plays BIGINT NOT NULL,
    PRIMARY KEY (user_id, artist, album),
    FOREIGN KEY (user_id) REFERENCES lastfm.config (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lastfm.tracks (
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    artist CITEXT NOT NULL,
    track CITEXT NOT NULL,
    plays BIGINT NOT NULL,
    PRIMARY KEY (user_id, artist, track),
    FOREIGN KEY (user_id) REFERENCES lastfm.config (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lastfm.crowns (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    artist CITEXT NOT NULL,
    claimed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, artist),
    FOREIGN KEY (user_id, artist) REFERENCES lastfm.artists (user_id, artist)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lastfm.hidden (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);


CREATE TABLE IF NOT EXISTS name_history (
  changed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
  is_nickname BOOLEAN NOT NULL DEFAULT FALSE,
  user_id BIGINT NOT NULL,
  username TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reaction_role (
  channel_id BIGINT NOT NULL,
  emoji TEXT NOT NULL,
  guild_id BIGINT NOT NULL,
  message_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS reaction_trigger (
  emoji TEXT NOT NULL,
  guild_id BIGINT NOT NULL,
  trigger CITEXT NOT NULL,
  PRIMARY KEY (guild_id, trigger, emoji)
);

CREATE SCHEMA IF NOT EXISTS reposters;

CREATE TABLE IF NOT EXISTS reposters.disabled (
  channel_id BIGINT NOT NULL,
  guild_id BIGINT NOT NULL,
  reposter TEXT NOT NULL,
  PRIMARY KEY (guild_id, channel_id, reposter)
);

CREATE TABLE IF NOT EXISTS response_trigger (
  delete BOOLEAN NOT NULL DEFAULT FALSE,
  delete_after INTEGER NOT NULL DEFAULT 0,
  guild_id BIGINT NOT NULL,
  reply BOOLEAN NOT NULL DEFAULT FALSE,
  role_id BIGINT,
  strict BOOLEAN NOT NULL DEFAULT FALSE,
  template TEXT NOT NULL,
  trigger CITEXT NOT NULL,
  PRIMARY KEY (guild_id, trigger)
);

CREATE SCHEMA IF NOT EXISTS snipe;

CREATE TABLE IF NOT EXISTS snipe.filter (
  guild_id BIGINT UNIQUE NOT NULL,
  invites BOOLEAN NOT NULL DEFAULT FALSE,
  links BOOLEAN NOT NULL DEFAULT FALSE,
  words TEXT[] NOT NULL DEFAULT '{}'::TEXT[]
);

CREATE TABLE IF NOT EXISTS snipe.ignore (
  guild_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, user_id)
);


CREATE TABLE IF NOT EXISTS settings (
  guild_id BIGINT NOT NULL,
  prefixes TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
  reskin BOOLEAN NOT NULL DEFAULT FALSE,
  reposter_prefix BOOLEAN NOT NULL DEFAULT TRUE,
  reposter_delete BOOLEAN NOT NULL DEFAULT FALSE,
  reposter_embed BOOLEAN NOT NULL DEFAULT TRUE,
  welcome_removal BOOLEAN NOT NULL DEFAULT FALSE,
  booster_role_base_id BIGINT,
  booster_role_include_ids BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  lock_role_id BIGINT,
  lock_ignore_ids BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  log_ignore_ids BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  reassign_ignore_ids BIGINT[] NOT NULL DEFAULT '{}'::BIGINT[],
  reassign_roles BOOLEAN NOT NULL DEFAULT FALSE,
  invoke_kick TEXT,
  invoke_ban TEXT,
  invoke_unban TEXT,
  invoke_timeout TEXT,
  invoke_untimeout TEXT,
  PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS sticky_message (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  message_id BIGINT NOT NULL,
  template TEXT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);


CREATE TABLE IF NOT EXISTS timezones (
    timezone TEXT NOT NULL,
    user_id BIGINT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS vanity (
  channel_id BIGINT,
  guild_id BIGINT UNIQUE NOT NULL,
  role_id BIGINT,
  template TEXT
);

CREATE TABLE IF NOT EXISTS welcome_message (
  channel_id BIGINT NOT NULL,
  delete_after INTEGER,
  guild_id BIGINT NOT NULL,
  template TEXT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE SCHEMA IF NOT EXISTS alerts;

CREATE TABLE IF NOT EXISTS alerts.twitch (
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    last_stream_id BIGINT,
    role_id BIGINT,
    template TEXT,
    twitch_id BIGINT NOT NULL,
    twitch_login TEXT NOT NULL,
    PRIMARY KEY (guild_id, twitch_id)
);

CREATE SCHEMA IF NOT EXISTS commands;

CREATE TABLE IF NOT EXISTS commands.usage (
  channel_id BIGINT NOT NULL,
  command TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  guild_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands.disabled (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    command TEXT NOT NULL,
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS commands.restricted (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    command TEXT NOT NULL,
    PRIMARY KEY (guild_id, role_id, command)
);

CREATE TABLE IF NOT EXISTS commands.ignore (
    guild_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, target_id)
);


CREATE TABLE IF NOT EXISTS giveaway (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    prize TEXT NOT NULL,
    emoji TEXT NOT NULL,
    winners INTEGER NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id)
);



CREATE TABLE IF NOT EXISTS counter (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  option TEXT NOT NULL,
  last_update TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  rate_limited_until TIMESTAMP WITH TIME ZONE,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS crypto (
  user_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  transaction_id TEXT NOT NULL,
  transaction_type TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, transaction_id)
);

CREATE SCHEMA IF NOT EXISTS reskin;

CREATE TABLE IF NOT EXISTS reskin.config (
  avatar_url TEXT,
  user_id BIGINT UNIQUE NOT NULL,
  username TEXT
);

CREATE TABLE IF NOT EXISTS reskin.webhook (
  channel_id BIGINT NOT NULL,
  guild_id BIGINT NOT NULL,
  webhook_id BIGINT NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS webhook (
  identifier TEXT NOT NULL,
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  author_id BIGINT NOT NULL,
  webhook_id BIGINT NOT NULL,
  PRIMARY KEY (channel_id, webhook_id)
);

CREATE TABLE IF NOT EXISTS highlights (
  guild_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  word TEXT NOT NULl,
  PRIMARY KEY (guild_id, user_id, word)
);

CREATE TABLE IF NOT EXISTS donators (
  user_id BIGINT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id)
);

CREATE SCHEMA IF NOT EXISTS timer;

CREATE TABLE IF NOT EXISTS timer.message (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  template TEXT NOT NULL,
  interval INTEGER NOT NULL,
  next_trigger TIMESTAMP WITH TIME ZONE NOT NULL,
  PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS timer.purge (
  guild_id BIGINT NOT NULL,
  channel_id BIGINT NOT NULL,
  interval INTEGER NOT NULL,
  next_trigger TIMESTAMP WITH TIME ZONE NOT NULL,
  method TEXT NOT NULL DEFAULT 'bulk',
  PRIMARY KEY (guild_id, channel_id)
);


CREATE SCHEMA IF NOT EXISTS voicemaster;

CREATE TABLE IF NOT EXISTS voicemaster.settings (
    guild_id BIGINT PRIMARY KEY,
    category_id BIGINT,
    jtc_channel_id BIGINT,
    interface_id BIGINT,
    default_role_id BIGINT,
    default_channel_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS voicemaster.channels (
    channel_id BIGINT PRIMARY KEY,
    guild_id BIGINT,
    owner_id BIGINT,
    FOREIGN KEY (guild_id) REFERENCES voicemaster.settings(guild_id)
);

CREATE TABLE IF NOT EXISTS voicemaster.roles (
    channel_id BIGINT PRIMARY KEY,
    role_id BIGINT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES voicemaster.channels (channel_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vape (
    guild_id BIGINT PRIMARY KEY,
    user_id BIGINT,
    hits INTEGER DEFAULT 0,
    flavor TEXT
);


CREATE TABLE IF NOT EXISTS pingonjoin (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    delete_after INTEGER
);

CREATE SCHEMA IF NOT EXISTS leveling;

CREATE TABLE IF NOT EXISTS leveling.setup (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    message TEXT,
    booster_boost BOOLEAN
);

CREATE TABLE IF NOT EXISTS leveling.user (
    guild_id BIGINT,
    user_id BIGINT,
    xp INTEGER,
    level INTEGER,
    target_xp INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS leveling.rewards (
    guild_id BIGINT,
    level INTEGER,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)
);

CREATE SCHEMA IF NOT EXISTS tickets;

CREATE TABLE IF NOT EXISTS tickets.setup (
    guild_id BIGINT PRIMARY KEY,
    category_id BIGINT,
    ticket_channel BIGINT,
    support_id BIGINT,
    logs BIGINT,
    open_embed TEXT
);

CREATE TABLE IF NOT EXISTS tickets.topics (
    guild_id BIGINT,
    name TEXT,
    description TEXT,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS tickets.opened (
    guild_id BIGINT,
    channel_id BIGINT,
    user_id BIGINT,
    PRIMARY KEY (guild_id, channel_id)
);