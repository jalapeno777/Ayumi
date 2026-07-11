FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Maven settings to allow Dukascopy HTTP repo
COPY settings.xml /root/.m2/settings.xml

# Copy pom first for dependency caching
COPY pom.xml .
RUN mvn dependency:resolve -q || true

# Copy source and build
COPY src ./src
RUN mvn package -DskipTests 2>&1 || (cat /root/.m2/settings.xml && exit 1)

# Output directory
RUN mkdir -p /data/output
VOLUME /data/output

# Default: small test batch (GBPUSD, 1 day)
ENV INSTRUMENTS=GBPUSD
ENV START_DATE=2024-06-01
ENV END_DATE=2024-06-02
ENV RATE_LIMIT_RPS=2.5
ENV BATCH_DAYS=1

ENTRYPOINT ["java", "-Dhttp.agent=Java Web Start/17.0", "-jar", "target/dukascopy-harvester-1.0.0.jar"]
