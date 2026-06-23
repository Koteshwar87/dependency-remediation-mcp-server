package com.example.sample;

import java.util.HashMap;
import java.util.Map;

import org.apache.commons.collections4.Bag;
import org.apache.commons.collections4.bag.HashBag;
import org.apache.commons.text.StringSubstitutor;
import org.springframework.stereotype.Service;

/**
 * Trivial service that genuinely exercises the two intentionally-old direct deps
 * (commons-text + commons-collections4) so they are real compile dependencies.
 */
@Service
public class GreetingService {

    /** Uses commons-text StringSubstitutor to render a templated greeting. */
    public String greet(String name) {
        Map<String, String> values = new HashMap<>();
        values.put("name", name);
        return new StringSubstitutor(values).replace("Hello, ${name}!");
    }

    /** Uses commons-collections4 Bag to count word occurrences. */
    public int countOccurrences(String word, String... words) {
        Bag<String> bag = new HashBag<>();
        for (String w : words) {
            bag.add(w);
        }
        return bag.getCount(word);
    }
}
