package com.ayumi.harvester;

import com.dukascopy.api.IBar;
import com.dukascopy.api.IContext;
import com.dukascopy.api.IHistory;
import com.dukascopy.api.IStrategy;
import com.dukascopy.api.ITick;
import com.dukascopy.api.Instrument;
import com.dukascopy.api.JFException;
import com.dukascopy.api.OfferSide;
import com.dukascopy.api.Period;
import com.dukascopy.api.system.ClientFactory;
import com.dukascopy.api.system.IClient;
import com.dukascopy.api.system.ISystemListener;

import java.io.BufferedWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Headless tick data harvester for Dukascopy JForex SDK 3.6.51.
 *
 * Pattern (per Dukascopy 3.x API):
 *   1. Get IClient from ClientFactory.getDefaultInstance()
 *   2. Register ISystemListener (NOT the legacy SystemOutListener)
 *   3. connect(jnlp, user, password) - jnlp is the FIRST arg
 *   4. setSubscribedInstruments(...) on the IClient
 *   5. startStrategy(IStrategy) - onStart(IContext) gives us IHistory
 *   6. IContext.getHistory().getTicks(Instrument, from, to)
 *   7. stopStrategy(id) + disconnect()
 *
 * Output: CSV files per (instrument, day) with columns
 *   timestamp,instrument,bid,ask,bidVol,askVol
 */
public class HarvesterMain {

    // ---- Config (env-driven) ------------------------------------------------
    static final String USERNAME      = System.getenv().getOrDefault("DUKA_USER", "");
    static final String PASSWORD      = System.getenv().getOrDefault("DUKA_PASS", "");
    // Demo JNLP by default; for LIVE set DUKA_JNLP=https://www.dukascopy.com/client/live/jclient/jforex.jnlp
    static final String JNLP_URL      = System.getenv().getOrDefault(
            "DUKA_JNLP", "https://www.dukascopy.com/client/demo/jclient/jforex.jnlp");
    static final String OUTPUT_DIR    = System.getenv().getOrDefault("OUTPUT_DIR", "/data/output");
    static final String INSTRUMENTS   = System.getenv().getOrDefault("INSTRUMENTS", "GBPUSD,USDJPY,EURUSD");
    static final String START_DATE    = System.getenv().getOrDefault("START_DATE", "2024-01-01");
    static final String END_DATE      = System.getenv().getOrDefault("END_DATE",   "2024-01-02");
    static final double RATE_LIMIT    = Double.parseDouble(
            System.getenv().getOrDefault("RATE_LIMIT_RPS", "2.5"));
    static final int    BATCH_DAYS    = Integer.parseInt(
            System.getenv().getOrDefault("BATCH_DAYS", "1"));
    // How long to wait after onConnect before fetching ticks (lets data feed prime)
    static final long   POST_CONNECT_SETTLE_MS = Long.parseLong(
            System.getenv().getOrDefault("POST_CONNECT_SETTLE_MS", "5000"));
    // Hard upper bound on a single getTicks() call. The SDK can occasionally hang
    // waiting for a response that the server never delivers (or the data feed never
    // "primes"). We run getTicks() on a worker thread and time it out here.
    static final long   GET_TICKS_TIMEOUT_SEC = Long.parseLong(
            System.getenv().getOrDefault("GET_TICKS_TIMEOUT_SEC", "15"));
    // How many times to retry a getTicks() call that returned empty / null / timed-out
    // before giving up on that batch.
    static final int    GET_TICKS_MAX_RETRIES = Integer.parseInt(
            System.getenv().getOrDefault("GET_TICKS_MAX_RETRIES", "1"));
    // How long to wait for the live tick feed to report at least one tick per
    // subscribed instrument after subscribe. The SDK logs DEBUG noise about
    // "Unrecognized protocol message : LastTickResponseMessage" while live ticks
    // stream in -- that's harmless, but we use the same path to confirm readiness.
    static final long   FEED_READY_TIMEOUT_SEC = Long.parseLong(
            System.getenv().getOrDefault("FEED_READY_TIMEOUT_SEC", "30"));
    // If true, fall back to Period.ONE_MIN bars if getTicks() fails permanently for a batch.
    static final boolean FALLBACK_TO_BARS = Boolean.parseBoolean(
            System.getenv().getOrDefault("FALLBACK_TO_BARS", "true"));

    static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    // ---- Main ---------------------------------------------------------------
    public static void main(String[] args) throws Exception {
        // Suppress the misleading "Unrecognized protocol message : LastTickResponseMessage"
        // DEBUG noise from DCClientImpl. The data IS being processed (we get it back from
        // getTicks()); the SDK just doesn't have a dedicated log path for these live-stream
        // messages and prints them at DEBUG. Lift the floor to WARN.
        java.util.logging.Logger root = java.util.logging.Logger.getLogger("");
        root.setLevel(java.util.logging.Level.WARNING);
        // SLF4J-simple / logback properties are read by the SDK's transport layer; this
        // works whether the JDK uses jul or slf4j.
        System.setProperty("org.slf4j.simpleLogger.defaultLogLevel", "warn");
        System.setProperty("org.slf4j.simpleLogger.log.com.dukascopy", "warn");

        log("=== Dukascopy Tick Harvester (SDK 3.6.51) ===");
        log("JNLP  : " + JNLP_URL);
        log("User  : " + USERNAME);
        log("Output: " + OUTPUT_DIR);
        log("Instrs: " + INSTRUMENTS);
        log("Range : " + START_DATE + " -> " + END_DATE);
        log("Rate  : " + RATE_LIMIT + " req/s");
        log("Batch : " + BATCH_DAYS + " day(s)");
        log("Per-call timeout: " + GET_TICKS_TIMEOUT_SEC + "s, retries=" + GET_TICKS_MAX_RETRIES
                + ", fallback_bars=" + FALLBACK_TO_BARS);

        if (USERNAME.isEmpty() || PASSWORD.isEmpty()) {
            log("ERROR: DUKA_USER and DUKA_PASS env vars required");
            System.exit(1);
        }

        // Parse instruments
        List<Instrument> instruments = new ArrayList<>();
        for (String s : INSTRUMENTS.split(",")) {
            s = s.trim().toUpperCase();
            if (s.isEmpty()) continue;
            try {
                instruments.add(Instrument.valueOf(s));
            } catch (IllegalArgumentException e) {
                log("WARN: Unknown instrument '" + s + "', skipping");
            }
        }
        if (instruments.isEmpty()) {
            log("ERROR: No valid instruments");
            System.exit(1);
        }

        // Parse dates
        final LocalDate start;
        final LocalDate end;
        try {
            start = LocalDate.parse(START_DATE, DATE_FMT);
            end   = LocalDate.parse(END_DATE,   DATE_FMT);
        } catch (Exception e) {
            log("ERROR: Bad date format (expected yyyy-MM-dd): " + e.getMessage());
            System.exit(1);
            return;
        }
        if (!end.isAfter(start)) {
            log("ERROR: END_DATE must be after START_DATE");
            System.exit(1);
        }

        // 1) IClient
        IClient client = ClientFactory.getDefaultInstance();

        // 2) System listener (wait for onConnect)
        CountDownLatch connected = new CountDownLatch(1);
        AtomicReference<String> disconnectReason = new AtomicReference<>(null);

        client.setSystemListener(new ISystemListener() {
            @Override public void onStart(long processId) {
                log("[JForex] strategy started, pid=" + processId);
            }
            @Override public void onStop(long processId) {
                log("[JForex] strategy stopped, pid=" + processId);
            }
            @Override public void onConnect() {
                log("[JForex] connected");
                connected.countDown();
            }
            @Override public void onDisconnect() {
                String r = "server disconnect";
                disconnectReason.set(r);
                log("[JForex] disconnected (" + r + ")");
            }
        });

        // 3) connect(jnlp, user, password)
        log("Connecting to Dukascopy...");
        try {
            client.connect(JNLP_URL, USERNAME, PASSWORD);
        } catch (Exception e) {
            log("FATAL: connect() failed: " + e.getClass().getSimpleName() + ": " + e.getMessage());
            System.exit(2);
        }

        // Wait up to 30s for onConnect
        if (!connected.await(30, TimeUnit.SECONDS)) {
            log("FATAL: timed out waiting for onConnect");
            try { client.disconnect(); } catch (Exception ignore) {}
            System.exit(2);
        }

        // Give the data feed a moment to prime
        log("Connection established, waiting " + POST_CONNECT_SETTLE_MS + "ms for feed to settle...");
        Thread.sleep(POST_CONNECT_SETTLE_MS);

        // 4) Subscribe instruments
        Set<Instrument> subscribed = new HashSet<>(instruments);
        client.setSubscribedInstruments(subscribed);
        log("Subscribed to: " + subscribed);

        // 5) startStrategy() - the onStart callback hands us an IContext with IHistory
        AtomicReference<IContext> contextRef = new AtomicReference<>(null);
        CountDownLatch strategyReady = new CountDownLatch(1);

        IStrategy harvestingStrategy = new IStrategy() {
            @Override public void onStart(IContext context) throws JFException {
                contextRef.set(context);
                strategyReady.countDown();
            }
            @Override public void onTick(Instrument instrument, ITick tick) throws JFException { /* no-op */ }
            @Override public void onBar(Instrument instrument, com.dukascopy.api.Period period,
                                        com.dukascopy.api.IBar askBar, com.dukascopy.api.IBar bidBar) throws JFException { /* no-op */ }
            @Override public void onMessage(com.dukascopy.api.IMessage message) throws JFException { /* no-op */ }
            @Override public void onAccount(com.dukascopy.api.IAccount account) throws JFException { /* no-op */ }
            @Override public void onStop() throws JFException { /* no-op */ }
        };

        long strategyId;
        try {
            strategyId = client.startStrategy(harvestingStrategy);
            log("Strategy started, id=" + strategyId);
        } catch (Exception e) {
            log("FATAL: startStrategy() failed: " + e.getMessage());
            try { client.disconnect(); } catch (Exception ignore) {}
            System.exit(3);
            return;
        }

        if (!strategyReady.await(30, TimeUnit.SECONDS)) {
            log("FATAL: strategy onStart never fired");
            try { client.stopStrategy(strategyId); client.disconnect(); } catch (Exception ignore) {}
            System.exit(3);
        }

        IContext ctx = contextRef.get();
        if (ctx == null) {
            log("FATAL: IContext is null");
            try { client.stopStrategy(strategyId); client.disconnect(); } catch (Exception ignore) {}
            System.exit(3);
        }
        IHistory history = ctx.getHistory();

        // Wait for the live tick feed to actually start delivering ticks for each
        // subscribed instrument. Without this, getTicks() can occasionally return null
        // (the SDK hasn't seen the instrument "live" yet). Bounded by FEED_READY_TIMEOUT_SEC.
        waitForFeedReady(history, instruments, FEED_READY_TIMEOUT_SEC);

        log("IHistory obtained, beginning harvest.");

        // 6) Harvest loop
        Path outDir = Paths.get(OUTPUT_DIR);
        Files.createDirectories(outDir);

        long minIntervalMs = (long) Math.ceil(1000.0 / RATE_LIMIT);
        AtomicLong lastRequestMs = new AtomicLong(0);
        AtomicInteger totalTicks = new AtomicInteger(0);
        AtomicInteger totalBars = new AtomicInteger(0);
        int totalBatches = 0;
        int totalErrors = 0;
        int totalFallbacks = 0;
        int totalEmpty = 0;

        ExecutorService getTicksPool = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "getTicks-worker");
            t.setDaemon(true);
            return t;
        });

        try {
            for (Instrument inst : instruments) {
                log("--- Harvesting " + inst.name() + " ---");
                LocalDate cursor = start;
                while (cursor.isBefore(end)) {
                    LocalDate batchEnd = cursor.plusDays(BATCH_DAYS);
                    if (batchEnd.isAfter(end)) batchEnd = end;

                    // Skip weekends (forex market closed Sat/Sun UTC)
                    java.time.DayOfWeek dow = cursor.getDayOfWeek();
                    if (dow == java.time.DayOfWeek.SATURDAY || dow == java.time.DayOfWeek.SUNDAY) {
                        cursor = batchEnd;
                        continue;
                    }

                    // Rate limit
                    long now = System.currentTimeMillis();
                    long sinceLast = now - lastRequestMs.get();
                    if (sinceLast < minIntervalMs) {
                        Thread.sleep(minIntervalMs - sinceLast);
                    }
                    lastRequestMs.set(System.currentTimeMillis());

                    long fromMs = cursor.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli();
                    long toMs   = batchEnd.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli();

                    totalBatches++;

                    List<ITick> ticks = null;
                    String ticksError = null;
                    for (int attempt = 1; attempt <= GET_TICKS_MAX_RETRIES; attempt++) {
                        try {
                            ticks = callGetTicksWithTimeout(getTicksPool, history, inst, fromMs, toMs,
                                    GET_TICKS_TIMEOUT_SEC);
                            if (ticks != null && !ticks.isEmpty()) break;
                            // null/empty -> retry after a short backoff
                            if (attempt < GET_TICKS_MAX_RETRIES) {
                                log("  " + inst.name() + " " + cursor.format(DATE_FMT)
                                        + " : empty result, retry " + attempt + "/" + GET_TICKS_MAX_RETRIES);
                                Thread.sleep(2000L * attempt);
                            }
                        } catch (Exception e) {
                            ticksError = e.getClass().getSimpleName() + ": " + e.getMessage();
                            log("  " + inst.name() + " " + cursor.format(DATE_FMT)
                                    + " : getTicks error attempt " + attempt + "/" + GET_TICKS_MAX_RETRIES
                                    + " -> " + ticksError);
                            if (attempt < GET_TICKS_MAX_RETRIES) {
                                Thread.sleep(2000L * attempt);
                            }
                        }
                    }

                    if (ticks != null && !ticks.isEmpty()) {
                        String filename = inst.name().replace("/", "") + "_"
                                + cursor.format(DateTimeFormatter.ofPattern("yyyyMMdd")) + ".csv";
                        Path outPath = outDir.resolve(filename);

                        try (BufferedWriter w = Files.newBufferedWriter(outPath)) {
                            w.write("timestamp,instrument,bid,ask,bidVol,askVol\n");
                            for (ITick t : ticks) {
                                w.write(String.format("%d,%s,%.5f,%.5f,%.2f,%.2f%n",
                                        t.getTime(),
                                        inst.name(),
                                        t.getBid(),
                                        t.getAsk(),
                                        t.getBidVolume(),
                                        t.getAskVolume()));
                            }
                        }
                        totalTicks.addAndGet(ticks.size());
                        log(String.format("  %s %s -> %s : %,d ticks -> %s",
                                inst.name(),
                                cursor.format(DATE_FMT),
                                batchEnd.format(DATE_FMT),
                                ticks.size(),
                                filename));
                    } else {
                        // Tick fetch failed or returned nothing. Try M1 bars as a fallback
                        // so we get *some* data for the day instead of dropping it.
                        // Skip fallback on timeout — if ticks timed out, bars will too (holiday/no data).
                        boolean fellBack = false;
                        boolean wasTimeout = ticksError != null && ticksError.contains("TimeoutException");
                        if (FALLBACK_TO_BARS && !wasTimeout) {
                            try {
                                List<IBar> bars = callGetBarsWithTimeout(getTicksPool, history, inst,
                                        Period.ONE_MIN, OfferSide.BID, fromMs, toMs, GET_TICKS_TIMEOUT_SEC);
                                if (bars != null && !bars.isEmpty()) {
                                    String filename = inst.name().replace("/", "") + "_"
                                            + cursor.format(DateTimeFormatter.ofPattern("yyyyMMdd"))
                                            + "_M1.csv";
                                    Path outPath = outDir.resolve(filename);
                                    try (BufferedWriter w = Files.newBufferedWriter(outPath)) {
                                        w.write("timestamp,instrument,open,high,low,close,volume\n");
                                        for (IBar b : bars) {
                                            w.write(String.format("%d,%s,%.5f,%.5f,%.5f,%.5f,%.2f%n",
                                                    b.getTime(),
                                                    inst.name(),
                                                    b.getOpen(), b.getHigh(), b.getLow(), b.getClose(),
                                                    b.getVolume()));
                                        }
                                    }
                                    totalBars.addAndGet(bars.size());
                                    totalFallbacks++;
                                    fellBack = true;
                                    log(String.format("  %s %s -> %s : FALLBACK %,d M1 bars -> %s (tick fetch %s)",
                                            inst.name(),
                                            cursor.format(DATE_FMT),
                                            batchEnd.format(DATE_FMT),
                                            bars.size(),
                                            filename,
                                            ticksError == null ? "empty" : "errored"));
                                }
                            } catch (Exception be) {
                                log("  " + inst.name() + " " + cursor.format(DATE_FMT)
                                        + " : fallback bars also failed: "
                                        + be.getClass().getSimpleName() + ": " + be.getMessage());
                            }
                        }
                        if (!fellBack) {
                            totalEmpty++;
                            totalErrors++;
                            log("  " + inst.name() + " " + cursor.format(DATE_FMT) + " -> "
                                    + batchEnd.format(DATE_FMT)
                                    + " : 0 ticks (empty range, weekend, or unrecoverable error"
                                    + (ticksError == null ? "" : ": " + ticksError) + ")");
                        }
                    }

                    cursor = batchEnd;
                }
            }
        } finally {
            getTicksPool.shutdownNow();
        }

        log("=== Harvest complete ===");
        log("Total ticks     : " + totalTicks.get());
        log("Total M1 bars   : " + totalBars.get() + " (fallback)");
        log("Total batches   : " + totalBatches);
        log("Empty/errored   : " + totalEmpty);
        log("Fallback batches: " + totalFallbacks);
        log("Output dir      : " + outDir.toAbsolutePath());

        // 7) Cleanup
        try { client.stopStrategy(strategyId); } catch (Exception ignore) {}
        try { client.disconnect(); }            catch (Exception ignore) {}

        if (totalTicks.get() == 0 && totalBars.get() == 0) {
            log("FAIL: no tick or bar data was harvested");
            System.exit(4);
        }
        if (totalEmpty > 0 && totalTicks.get() == 0) {
            System.exit(4);
        }
        System.exit(0);
    }

    /**
     * Runs IHistory.getTicks() on a worker thread so we can apply a hard timeout.
     * The SDK's getTicks() can occasionally hang if the live tick feed isn't ready
     * or if the server stalls on the response.
     */
    static List<ITick> callGetTicksWithTimeout(ExecutorService pool, IHistory history,
                                               Instrument inst, long from, long to, long timeoutSec)
            throws InterruptedException, ExecutionException, TimeoutException {
        Callable<List<ITick>> task = () -> history.getTicks(inst, from, to);
        Future<List<ITick>> f = pool.submit(task);
        try {
            return f.get(timeoutSec, TimeUnit.SECONDS);
        } catch (TimeoutException te) {
            f.cancel(true);
            throw te;
        }
    }

    static List<IBar> callGetBarsWithTimeout(ExecutorService pool, IHistory history, Instrument inst,
                                             Period period, OfferSide side, long from, long to,
                                             long timeoutSec)
            throws InterruptedException, ExecutionException, TimeoutException {
        Callable<List<IBar>> task = () -> history.getBars(inst, period, side, from, to);
        Future<List<IBar>> f = pool.submit(task);
        try {
            return f.get(timeoutSec, TimeUnit.SECONDS);
        } catch (TimeoutException te) {
            f.cancel(true);
            throw te;
        }
    }

    /**
     * Polls IHistory.getLastTick() per subscribed instrument until each one returns
     * a non-null tick, or we hit FEED_READY_TIMEOUT_SEC. This guards against the case
     * where the strategy starts but the SDK's live tick stream hasn't actually primed
     * yet -- without this, the very first getTicks() call can hang.
     */
    static void waitForFeedReady(IHistory history, List<Instrument> instruments, long timeoutSec) {
        long deadline = System.currentTimeMillis() + timeoutSec * 1000L;
        Set<Instrument> pending = new HashSet<>(instruments);
        while (!pending.isEmpty() && System.currentTimeMillis() < deadline) {
            for (Instrument inst : new ArrayList<>(pending)) {
                try {
                    ITick last = history.getLastTick(inst);
                    if (last != null && last.getTime() > 0) {
                        log("  feed ready: " + inst.name() + " lastTick time=" + last.getTime());
                        pending.remove(inst);
                    }
                } catch (JFException e) {
                    // not ready yet, keep trying
                } catch (Exception e) {
                    log("  feed ready check error " + inst.name() + ": "
                            + e.getClass().getSimpleName() + ": " + e.getMessage());
                }
            }
            if (!pending.isEmpty()) {
                try { Thread.sleep(1000); } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
        if (!pending.isEmpty()) {
            log("WARN: feed not fully ready after " + timeoutSec + "s, proceeding anyway. Pending: "
                    + pending);
        }
    }

    static void log(String msg) {
        System.out.println("[" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm:ss"))
                + "] " + msg);
    }
}