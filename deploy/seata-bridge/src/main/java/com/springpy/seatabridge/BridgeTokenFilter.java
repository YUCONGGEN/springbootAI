package com.springpy.seatabridge;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class BridgeTokenFilter extends OncePerRequestFilter {

    private final byte[] expectedToken;

    public BridgeTokenFilter(@Value("${bridge.token:}") String token) {
        this.expectedToken = token.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return "/health".equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        String provided = request.getHeader("X-Seata-Bridge-Token");
        byte[] providedBytes = provided == null
                ? new byte[0]
                : provided.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expectedToken, providedBytes)) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\":\"invalid bridge token\"}");
            return;
        }
        filterChain.doFilter(request, response);
    }
}
