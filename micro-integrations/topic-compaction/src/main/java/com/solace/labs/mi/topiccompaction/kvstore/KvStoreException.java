package com.solace.labs.mi.topiccompaction.kvstore;

/**
 * Unchecked wrapper for KV-store backend exceptions.
 */
public class KvStoreException extends RuntimeException {
    public KvStoreException(String message, Throwable cause) {
        super(message, cause);
    }
}
