package com.example.sample;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class GreetingServiceTest {

    private final GreetingService service = new GreetingService();

    @Test
    void greetsByName() {
        assertEquals("Hello, world!", service.greet("world"));
    }

    @Test
    void countsOccurrences() {
        assertEquals(2, service.countOccurrences("a", "a", "b", "a"));
    }
}
