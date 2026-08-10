package com.springpy.seatabridge;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class SeataBridgeApplication {

    public static void main(String[] args) {
        SpringApplication.run(SeataBridgeApplication.class, args);
    }

    @Bean
    ApplicationRunner validateSecurityConfiguration(
            @Value("${bridge.token:}") String token,
            @Value("${bridge.callback-allowed-hosts:}") String callbackAllowedHosts) {
        return new ApplicationRunner() {
            @Override
            public void run(ApplicationArguments args) {
                if (token.length() < 16) {
                    throw new IllegalStateException("BRIDGE_TOKEN must contain at least 16 characters");
                }
                if (callbackAllowedHosts.isBlank()) {
                    throw new IllegalStateException("BRIDGE_CALLBACK_ALLOWED_HOSTS must not be empty");
                }
            }
        };
    }
}
