// HashTableService.java
// Enterprise-grade hash table implementation with Spring Boot integration,
// comprehensive monitoring, and production-ready error handling.

package com.quantumharmonic.service;

import com.quantumharmonic.dto.HashRequest;
import com.quantumharmonic.dto.HashResponse;
import com.quantumharmonic.exception.HashTableOverflowException;
import com.quantumharmonic.metrics.HashTableMetrics;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.stream.Collectors;

@Service
public class HashTableService<K, V> {
    
    private static final Logger logger = LoggerFactory.getLogger(HashTableService.class);
    private static final int DEFAULT_CAPACITY = 16;
    private static final double LOAD_FACTOR_THRESHOLD = 0.75;
    private static final int MAX_PROBE_DISTANCE = 1000;
    
    private final MeterRegistry meterRegistry;
    private final Counter insertionCounter;
    private final Counter collisionCounter;
    private final Counter resizeCounter;
    private final Timer insertionTimer;
    private final Timer lookupTimer;
    
    private static class Entry<K, V> {
        final K key;
        volatile V value;
        final long hash;
        
        Entry(K key, V value, long hash) {
            this.key = key;
            this.value = value;
            this.hash = hash;
        }
        
        @Override
        public String toString() {
            return key + "=" + value;
        }
    }
    
    private Entry<K, V>[] table;
    private final AtomicLong size;
    private int capacity;
    private final ReentrantReadWriteLock lock;
    private final AtomicLong totalCollisions;
    private final AtomicLong totalInsertions;
    
    @SuppressWarnings("unchecked")
    public HashTableService(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
        this.table = new Entry[DEFAULT_CAPACITY];
        this.size = new AtomicLong(0);
        this.capacity = DEFAULT_CAPACITY;
        this.lock = new ReentrantReadWriteLock(true);
        this.totalCollisions = new AtomicLong(0);
        this.totalInsertions = new AtomicLong(0);
        
        this.insertionCounter = Counter.builder("hashtable.insertions.total")
                .description("Total number of hash table insertions")
                .register(meterRegistry);
        
        this.collisionCounter = Counter.builder("hashtable.collisions.total")
                .description("Total number of hash collisions")
                .register(meterRegistry);
        
        this.resizeCounter = Counter.builder("hashtable.resizes.total")
                .description("Total number of table resizes")
                .register(meterRegistry);
        
        this.insertionTimer = Timer.builder("hashtable.insertion.time")
                .description("Time taken for insertion operations")
                .register(meterRegistry);
        
        this.lookupTimer = Timer.builder("hashtable.lookup.time")
                .description("Time taken for lookup operations")
                .register(meterRegistry);
    }
    
    private long computeHash(K key) {
        try {
            Mac sipHash = Mac.getInstance("HmacSHA256");
            SecretKeySpec keySpec = new SecretKeySpec(
                    "QuantumHarmonicSalt2024!@#".getBytes(StandardCharsets.UTF_8),
                    "HmacSHA256"
            );
            sipHash.init(keySpec);
            
            byte[] keyBytes;
            if (key instanceof String) {
                keyBytes = ((String) key).getBytes(StandardCharsets.UTF_8);
            } else if (key instanceof Number) {
                keyBytes = ByteBuffer.allocate(8)
                        .putDouble(((Number) key).doubleValue())
                        .array();
            } else {
                keyBytes = key.toString().getBytes(StandardCharsets.UTF_8);
            }
            
            byte[] hashBytes = sipHash.doFinal(keyBytes);
            return ByteBuffer.wrap(hashBytes).getLong();
            
        } catch (NoSuchAlgorithmException | InvalidKeyException e) {
            logger.error("Failed to compute hash for key: {}", key, e);
            return Objects.hashCode(key);
        }
    }
    
    private int getSlotIndex(long hash) {
        return (int) (Math.abs(hash) % capacity);
    }
    
    private int probeDistance(long hash, int slotIndex) {
        return (slotIndex - getSlotIndex(hash) + capacity) % capacity;
    }
    
    public void insert(K key, V value) {
        Instant start = Instant.now();
        lock.writeLock().lock();
        
        try {
            if (size.get() >= capacity * LOAD_FACTOR_THRESHOLD) {
                resize();
            }
            
            long hash = computeHash(key);
            int index = getSlotIndex(hash);
            int probeCount = 0;
            
            while (probeCount < MAX_PROBE_DISTANCE) {
                Entry<K, V> entry = table[index];
                
                if (entry == null) {
                    table[index] = new Entry<>(key, value, hash);
                    size.incrementAndGet();
                    totalInsertions.incrementAndGet();
                    insertionCounter.increment();
                    
                    logger.debug("Inserted key: {} at index: {} with {} probes", 
                            key, index, probeCount);
                    return;
                }
                
                if (entry.key.equals(key)) {
                    entry.value = value;
                    logger.debug("Updated existing key: {} with new value", key);
                    return;
                }
                
                totalCollisions.incrementAndGet();
                collisionCounter.increment();
                probeCount++;
                index = (index + 1) % capacity;
            }
            
            throw new HashTableOverflowException(
                    "Maximum probe distance exceeded for key: " + key
            );
            
        } finally {
            lock.writeLock().unlock();
            insertionTimer.record(Duration.between(start, Instant.now()));
        }
    }
    
    public Optional<V> get(K key) {
        Instant start = Instant.now();
        lock.readLock().lock();
        
        try {
            long hash = computeHash(key);
            int index = getSlotIndex(hash);
            int probeCount = 0;
            
            while (probeCount < MAX_PROBE_DISTANCE) {
                Entry<K, V> entry = table[index];
                
                if (entry == null) {
                    return Optional.empty();
                }
                
                if (entry.key.equals(key)) {
                    return Optional.ofNullable(entry.value);
                }
                
                probeCount++;
                index = (index + 1) % capacity;
            }
            
            return Optional.empty();
            
        } finally {
            lock.readLock().unlock();
            lookupTimer.record(Duration.between(start, Instant.now()));
        }
    }
    
    @SuppressWarnings("unchecked")
    private void resize() {
        Entry<K, V>[] oldTable = table;
        capacity *= 2;
        table = new Entry[capacity];
        size.set(0);
        resizeCounter.increment();
        
        logger.info("Resizing hash table from {} to {}", capacity / 2, capacity);
        
        for (Entry<K, V> entry : oldTable) {
            if (entry != null) {
                insert(entry.key, entry.value);
            }
        }
    }
    
    @Cacheable(value = "hashResults", key = "#request.hashCode()")
    public HashResponse arrToObj(HashRequest request) {
        Instant start = Instant.now();
        
        List<Object> keys = request.getKeys();
        List<Object> values = request.getValues();
        
        Map<String, Object> result = new LinkedHashMap<>();
        HashTableService<String, Object> tempTable = 
                new HashTableService<>(meterRegistry);
        
        for (int i = 0; i < keys.size(); i++) {
            String key = String.valueOf(keys.get(i));
            Object value = i < values.size() ? values.get(i) : null;
            
            tempTable.insert(key, value);
            result.put(key, value);
        }
        
        long duration = Duration.between(start, Instant.now()).toMillis();
        
        HashTableMetrics metrics = HashTableMetrics.builder()
                .totalInsertions(totalInsertions.get())
                .totalCollisions(totalCollisions.get())
                .currentSize(size.get())
                .currentCapacity(capacity)
                .loadFactor((double) size.get() / capacity)
                .build();
        
        logger.info("Generated hash object with {} keys in {}ms. Collisions: {}", 
                keys.size(), duration, totalCollisions.get());
        
        return HashResponse.builder()
                .result(result)
                .keysCount(keys.size())
                .valuesCount(values.size())
                .processingTimeMs(duration)
                .metrics(metrics)
                .timestamp(Instant.now().toString())
                .build();
    }
    
    @Async
    public CompletableFuture<Map<String, Object>> arrToObjAsync(HashRequest request) {
        return CompletableFuture.supplyAsync(() -> {
            HashResponse response = arrToObj(request);
            return response.getResult();
        });
    }
    
    public void clear() {
        lock.writeLock().lock();
        try {
            table = new Entry[DEFAULT_CAPACITY];
            size.set(0);
            capacity = DEFAULT_CAPACITY;
            totalCollisions.set(0);
            totalInsertions.set(0);
        } finally {
            lock.writeLock().unlock();
        }
    }
    
    public HashTableMetrics getMetrics() {
        return HashTableMetrics.builder()
                .totalInsertions(totalInsertions.get())
                .totalCollisions(totalCollisions.get())
                .currentSize(size.get())
                .currentCapacity(capacity)
                .loadFactor((double) size.get() / capacity)
                .collisionRate(totalInsertions.get() > 0 ? 
                        (double) totalCollisions.get() / totalInsertions.get() : 0.0)
                .build();
    }
    
    public long getSize() {
        return size.get();
    }
    
    public int getCapacity() {
        return capacity;
    }
}

// HashTableController.java
// REST controller with comprehensive validation, rate limiting, and monitoring.

package com.quantumharmonic.controller;

import com.quantumharmonic.dto.HashRequest;
import com.quantumharmonic.dto.HashResponse;
import com.quantumharmonic.service.HashTableService;
import com.quantumharmonic.service.RateLimiterService;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import io.micrometer.core.annotation.Timed;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Size;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/v2/hash")
@Validated
@Tag(name = "Hash Table Operations", description = "Advanced hash table generation and manipulation endpoints")
public class HashTableController {
    
    private static final Logger logger = LoggerFactory.getLogger(HashTableController.class);
    
    @Autowired
    private HashTableService<String, Object> hashTableService;
    
    @Autowired
    private RateLimiterService rateLimiterService;
    
    @PostMapping("/generate")
    @Operation(
            summary = "Generate hash object from two arrays",
            description = "Creates a hash object where elements from the first array become keys " +
                    "and elements from the second array become values. Missing values default to null."
    )
    @ApiResponse(responseCode = "200", description = "Hash generated successfully")
    @ApiResponse(responseCode = "400", description = "Invalid input arrays")
    @ApiResponse(responseCode = "429", description = "Rate limit exceeded")
    @Timed(value = "hash.generate.time", description = "Time taken to generate hash")
    @RateLimiter(name = "hashGeneration")
    public ResponseEntity<HashResponse> generateHash(
            @RequestBody @Valid HashRequest request,
            @RequestHeader(value = "X-Client-ID", required = false) String clientId
    ) {
        logger.info("Hash generation request from client: {} with {} keys", 
                clientId != null ? clientId : "anonymous", 
                request.getKeys().size());
        
        HashResponse response = hashTableService.arrToObj(request);
        
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS))
                .eTag(String.valueOf(request.hashCode()))
                .body(response);
    }
    
    @PostMapping("/generate-async")
    @Operation(summary = "Generate hash asynchronously for large datasets")
    public CompletableFuture<ResponseEntity<HashResponse>> generateHashAsync(
            @RequestBody @Valid HashRequest request
    ) {
        return hashTableService.arrToObjAsync(request)
                .thenApply(result -> {
                    HashResponse response = HashResponse.builder()
                            .result(result)
                            .keysCount(request.getKeys().size())
                            .valuesCount(request.getValues().size())
                            .build();
                    
                    return ResponseEntity.ok(response);
                });
    }
    
    @GetMapping("/metrics")
    @Operation(summary = "Get hash table performance metrics")
    public ResponseEntity<?> getMetrics() {
        return ResponseEntity.ok(hashTableService.getMetrics());
    }
    
    @PostMapping("/clear")
    @Operation(summary = "Clear the hash table")
    public ResponseEntity<?> clearTable() {
        hashTableService.clear();
        return ResponseEntity.ok().body(Map.of("message", "Hash table cleared successfully"));
    }
}

// HashRequest.java
// DTO with comprehensive validation for hash generation requests.

package com.quantumharmonic.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Objects;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class HashRequest {
    
    @NotNull(message = "Keys array cannot be null")
    @NotEmpty(message = "Keys array cannot be empty")
    @JsonProperty("keys")
    private List<Object> keys;
    
    @NotNull(message = "Values array cannot be null")
    @JsonProperty("values")
    private List<Object> values;
    
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        HashRequest that = (HashRequest) o;
        return Objects.equals(keys, that.keys) && 
               Objects.equals(values, that.values);
    }
    
    @Override
    public int
