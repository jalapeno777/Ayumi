# Plan: CRYPTO — Set Up Telegram Broadcast Channel

**Issue:** [AYUAA-513](/AYUAA/issues/AYUAA-513)
**Status:** in_progress

## Objective
Create and configure a Telegram broadcast channel for instant crypto signal alerts, integrated with the existing Discord community.

## Tasks

### 1. Telegram Bot Setup
- [ ] Create bot via @BotFather on Telegram
- [ ] Get bot token and configure bot settings
- [ ] Set bot profile picture and description

### 2. Channel Creation
- [ ] Create Telegram broadcast channel (e.g., "Piggy Bank Academy Signals")
- [ ] Add bot as admin to channel
- [ ] Configure channel branding (name, description, photo)

### 3. Discord Integration
- [ ] Set up Discord-Telegram bridge using a bot like DiscordChatTracker or Telegram-to-Discord relay
- [ ] Configure which Discord channels sync to Telegram
- [ ] Test bidirectional notification flow

### 4. Auto-Post Configuration
- [ ] Connect bot to signal source (manual initially, automated later)
- [ ] Format signals with consistent template (pair, direction, entry, SL, TP)
- [ ] Set up scheduling for signal broadcasts

### 5. Onboarding Template
- [ ] Create welcome message for new channel members
- [ ] Create link-back to Discord for discussion
- [ ] Create subscription tier messaging (free vs VIP)

## Signal Format Template
```
🟢 SIGNAL ALERT

📊 Pair: [PAIR]
📈 Direction: LONG/SHORT
💰 Entry: [PRICE]
🛑 Stop Loss: [SL]
🎯 Take Profit: [TP]
⏰ Timeframe: [TF]

🔗 Join Discussion: [DISCORD_LINK]
```

## Channel Branding
- **Name:** Piggy Bank Academy | Crypto Signals
- **Bio:** Real-time crypto trade signals. Free daily alerts. Join the discussion on Discord!
- **Pinned Message:** Onboarding instructions with Discord link

## Deliverables
- Bot token (stored securely)
- Channel invite link
- Onboarding welcome message
- Signal format template
- Discord bridge setup documentation
