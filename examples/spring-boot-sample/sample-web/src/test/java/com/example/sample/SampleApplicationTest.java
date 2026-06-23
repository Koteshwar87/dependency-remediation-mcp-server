package com.example.sample;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * Loads the full Spring context, which starts embedded Tomcat — so an incompatible
 * tomcat-embed-core pin would fail here at runtime, not just at compile time.
 */
@SpringBootTest
class SampleApplicationTest {

    @Test
    void contextLoads() {
    }
}
