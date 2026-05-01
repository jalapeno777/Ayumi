# Week 1 Community Growth Sprint — Execution Guide

## Overview
This guide helps team members execute Day 1-14 activities for Week 1 Community Growth Sprint.

## Current Status (Technical Platform)
- ✅ Database operational with full schema
- ✅ API endpoints live and tested
- ✅ Referral system functional
- ✅ 47/47 tests passing
- ✅ Metrics tracker created

## Required Access & Credentials

### Discord
- **Role:** Community Manager or Admin
- **Access:** Post to #announcements, create channels
- **Actions:** Post referral announcement, create crypto channels

### Telegram
- **BotFather:** @BotFather (create bot)
- **Channel:** Create "Piggy Bank Academy | Crypto Signals"
- **Bot Token:** Required for script posting
- **Channel ID:** Required for bot configuration

### Email Service
- **Provider:** SendGrid or Mailgun recommended
- **API Key:** Required for automated onboarding
- **From Email:** noreply@piggybankacademy.com
- **Templates:** Ready in docs/media/email-onboarding-sequence.md

## Daily Execution Steps

### Day 1 (Today)
1. ☐ **Post Referral Program Launch to Discord**
   - Go to Piggy Bank Academy Discord
   - Post announcement in #announcements
   - Use content from docs/media/referral-program-launch-announcement.md
   - Pin the announcement for visibility

2. ☐ **Create Telegram Bot**
   - Message @BotFather: /newbot
   - Name: Piggy Bank Crypto Bot
   - Get bot token
   - Save token securely (never commit to git)

3. ☐ **Create Telegram Broadcast Channel**
   - Create channel: "Piggy Bank Academy | Crypto Signals"
   - Add bot as admin
   - Get channel ID (use @getidsbot)
   - Save channel ID for configuration

4. ☐ **Post Initial Telegram Messages**
   - Welcome message (9:00 AM UTC)
   - Referral program launch (12:00 PM UTC)  
   - First crypto signal (3:00 PM UTC)
   - Use content from docs/media/week-1-telegram-content-calendar.md

### Day 2-3
1. ☐ **Configure Email Service**
   - Set up SendGrid/Mailgun account
   - Create API key
   - Configure email templates
   - Test delivery to test email address

2. ☐ **Activate Onboarding Sequence**
   - Configure automation triggers
   - Test full 7-email sequence
   - Verify personalization variables work

3. ☐ **Set Up Discord-Telegram Bridge**
   - Configure Discord webhook URL
   - Test bidirectional sync
   - Define which channels sync to Telegram
   - Test signal auto-posting

### Day 4-7
1. ☐ **Create Discord Crypto Channels**
   - Create #crypto-signals
   - Create #crypto-discussion
   - Set up role-based access (Free, Pro, VIP)
   - Post cross-promotion content

2. ☐ **Configure Metrics Dashboard**
   - Set up real-time referral stats
   - Configure user acquisition tracking
   - Set up engagement metrics (DAU/MAU)
   - Create weekly reporting automation

3. ☐ **Continue Telegram Content**
   - Post daily per calendar
   - Track engagement metrics
   - Optimize content based on performance

## Running Metrics Tracker

Track daily progress:
```bash
cd /home/TacoPants/projects/Ayumi/worktrees/nash
python3 scripts/week1_metrics_tracker.py
```

This will show:
- Current metrics vs targets
- Progress percentages
- Daily priorities
- Recommendations

## Testing the Platform

### Test Referral System
```bash
cd /home/TacoPants/projects/Ayumi/worktrees/nash
python3 scripts/test_referral_system.py
```

### Start Dashboard Server
```bash
cd /home/TacoPants/projects/Ayumi/worktrees/nash
python3 -m src.crypto.bot
```
Server runs on: http://localhost:8080

### API Endpoints Available
- GET / — Leaderboard page
- GET /pricing — Subscription pricing
- GET /api/leaderboard — Provider stats
- GET /api/signals — Recent signals
- GET /api/providers/{id}/stats — Individual provider
- POST /api/users — User registration
- GET /api/referral/{code} — Validate referral
- GET /api/users/{id}/referral-stats — User statistics
- GET /api/pending-payouts — Payout management
- POST /api/payouts/{id}/mark-paid — Complete payout

## Success Criteria Checkpoints

### Day 3 Checkpoint
- [ ] Referral program live with 10+ active referrers
- [ ] Telegram channel operational with 25+ members
- [ ] Email sequence active and sending
- [ ] Discord integration tested and working

### Day 7 Checkpoint
- [ ] All Week 1 Telegram content posted
- [ ] 50+ Telegram channel members
- [ ] 25+ new Discord members
- [ ] 25+ new platform signups
- [ ] 10+ referral conversions
- [ ] $50+ pending commissions

### Day 14 Checkpoint
- [ ] Week 1 metrics report generated
- [ ] Top-performing content identified
- [ ] Optimization strategies documented
- [ ] Week 2 plan refined based on data

## Troubleshooting

### Discord Issues
- **Can't post:** Check role permissions
- **No engagement:** Test in smaller channels first
- **Links blocked:** Use URL shorteners or mention they can DM for link

### Telegram Issues
- **Bot not posting:** Check bot token and channel ID
- **No members:** Share channel link in Discord announcements
- **Content not visible:** Verify bot is admin in channel

### Email Issues
- **Not delivering:** Check SPF/DKIM records
- **Going to spam:** Test content with mail tester tools
- **Not personalizing:** Verify template variables are correct

### API Issues
- **500 errors:** Check server logs: `tail logs/crypto_bot.log`
- **Database locked:** Restart application
- **Referral tracking:** Verify referral codes are active in DB

## Resources

- [Full Execution Plan](/home/TacoPants/projects/Ayumi/worktrees/nash/docs/plans/week-1-community-growth-execution.md)
- [Executive Summary](/home/TacoPants/projects/Ayumi/worktrees/nash/docs/plans/week-1-executive-summary.md)
- [Referral Announcement](/home/TacoPants/projects/Ayumi/worktrees/nash/docs/media/referral-program-launch-announcement.md)
- [Telegram Content](/home/TacoPants/projects/Ayumi/worktrees/nash/docs/media/week-1-telegram-content-calendar.md)
- [Email Sequence](/home/TacoPants/projects/Ayumi/worktrees/nash/docs/media/email-onboarding-sequence.md)

## Team Coordination

### Who Does What

**Nash (Crypto Division Lead):**
- Technical platform maintenance
- Metrics tracking and reporting
- API support and troubleshooting

**Community Manager:**
- Discord posting and moderation
- Telegram channel management
- Community engagement and support

**Technical Team:**
- Email service configuration
- Metrics dashboard setup
- Discord-Telegram bridge setup

**Media Manager:**
- TikTok/YouTube cross-promotion
- Content optimization based on metrics
- Additional promotional content creation

## Daily Reporting Format

Post updates in #crypto-discussion each day:

```
Week 1 — Day [X] Update

✅ Completed:
- [Action 1]
- [Action 2]

📊 Metrics:
- New Signups: X
- Referral Conversions: X  
- Telegram Members: X
- Discord New Members: X

🚧 Blockers:
- [Any issues]

📅 Tomorrow:
- [Priority actions]
```

## Emergency Contacts

If critical issues arise:
1. Post in team Discord channel immediately
2. Escalate to Nori (Chief of Staff) within 4 hours
3. Document all issues for retrospective

