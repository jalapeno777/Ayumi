# Spotware QuickFIX/N .NET Samples Analysis

Source: https://github.com/spotware/quickfixnsamples.net

## Key Findings

### 1. Connection Configuration (Config.cfg template)

```
[DEFAULT]
ConnectionType=initiator
SocketConnectHost=<host>        # Plain text, NOT SSL
SocketConnectPort=<port>
ResetOnLogon=Y
ResetOnDisconnect=Y
DataDictionary=./FIX44-CSERVER.xml

[SESSION]
BeginString=FIX.4.4
SenderCompID=<from Spotware>
SenderSubID=TRADE               # For trading; use QUOTE for quotes
TargetSubID=TRADE                # Matches SenderSubID
TargetCompID=cServer             # ⚠️ Lowercase 'c', not 'CSERVER'
HeartBtInt=30
```

### 2. Authentication — Tags 553/554 ARE Used

In `QuickFixNApp.ToAdmin()`, the official sample **does send Username (553) and Password (554)** on the Logon (type A) message. They also explicitly re-set the header fields:

```csharp
message.SetField(new StringField(49, _senderCompId), true);   // SenderCompID
message.SetField(new StringField(56, _targetCompId), true);    // TargetCompID
message.SetField(new StringField(50, _senderSubId), true);     // SenderSubID
message.SetField(new StringField(52, <timestamp>), true);      // SendingTime
message.SetField(new StringField(553, _username), true);       // Username
message.SetField(new StringField(554, _password), true);       // Password
```

**So 553/554 is correct.** The "Can't route request" error is NOT caused by including these tags.

### 3. TargetCompID = "cServer" (NOT "CSERVER")

**This is the critical difference.** The official Spotware sample uses:
- `TargetCompID=cServer` (mixed case: lowercase `c`, uppercase `Server`)

Our v2 script likely used `CSERVER` (all uppercase). FIX field values are case-sensitive strings. If the server matches TargetCompID exactly, `CSERVER` ≠ `cServer` and the server would reject/route the message.

### 4. SenderSubID / TargetSubID Pattern

The sample uses:
- `SenderSubID=TRADE` and `TargetSubID=TRADE` for trading
- For quotes: change both to the quote credentials

The `SessionSettingsFactory` takes both as parameters, meaning the SubID values matter for routing.

### 5. No Special BodyLength Handling

QuickFIX/N handles BodyLength (tag 9) and CheckSum (tag 10) automatically. The sample does NOT manually calculate BodyLength — the library does it after all fields are set in `ToAdmin()`.

**For our raw Python script:** we must recalculate BodyLength AFTER adding 553/554 to the body. If we calculated it before adding those tags, the BodyLength would be wrong, and the server would reject the message.

### 6. Message Construction Order

The sample's `ToAdmin()` runs BEFORE the message is serialized and sent. The order:
1. QuickFIX/N builds the Logon message (EncryptMethod, HeartBtInt, etc.)
2. `ToAdmin()` callback fires — adds 49, 56, 50, 52, 553, 554
3. QuickFIX/N calculates BodyLength and CheckSum
4. Message is sent over the wire

### 7. Data Dictionary

They use a custom `FIX44-CSERVER.xml` data dictionary. The Logon message definition includes Username (553) and Password (554) as optional fields — confirming they belong in the Logon body.

## Comparison with Our v2 Implementation

| Aspect | Spotware Sample | Our v2 Script | Issue? |
|--------|----------------|---------------|--------|
| TargetCompID | `cServer` | `CSERVER` | **⚠️ LIKELY CAUSE** |
| Tags 553/554 | ✅ On Logon | ✅ On Logon | OK |
| SenderSubID | `TRADE` | ? | Check |
| TargetSubID | `TRADE` | ? | Check |
| BodyLength calc | After all fields | Before 553/554? | **⚠️ CHECK THIS** |
| BeginString | `FIX.4.4` | `FIX.4.4` | OK |
| HeartBtInt | `30` | ? | Check |

## Recommendations

1. **Fix TargetCompID**: Change from `CSERVER` to `cServer` — this is the most likely cause of "Can't route request"
2. **Verify BodyLength**: Ensure BodyLength is calculated AFTER all body fields (including 553/554) are added
3. **Check SenderSubID/TargetSubID**: Set both to `TRADE` for trading connections
4. **Use FIX 4.4**: Confirm we're using `FIX.4.4` not `FIXT.1.1`
