FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml ./
COPY settings.xml ./
RUN mvn -s settings.xml -B -q dependency:go-offline
COPY src ./src
RUN mvn -s settings.xml -B -q -DskipTests package

FROM eclipse-temurin:17-jre-alpine
RUN addgroup -S springpy && adduser -S springpy -G springpy
WORKDIR /app
COPY --from=build /workspace/target/seata-bridge-1.0.0.jar /app/seata-bridge.jar
USER springpy
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "/app/seata-bridge.jar"]
