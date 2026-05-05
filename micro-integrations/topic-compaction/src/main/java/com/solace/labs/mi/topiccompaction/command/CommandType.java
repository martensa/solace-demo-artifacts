package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.annotation.JsonCreator;

/**
 * Set of accepted command verbs.
 *
 * <p>V1.0 ships {@link #REPLAY}, {@link #BULK_REPLAY}, and
 * {@link #DELETE}. Future verbs can be added without breaking the
 * wire protocol thanks to JSON-Schema validation at the boundary.
 */
public enum CommandType {

    /** Replay the latest record for a single key. */
    REPLAY,

    /** Replay every key matching a Solace topic pattern. */
    BULK_REPLAY,

    /** Tombstone a single key (and optionally a pattern via cascade). */
    DELETE;

    /**
     * Case-insensitive parse so callers can write {@code "replay"} or
     * {@code "Replay"} without surprises. Schema validation rejects
     * unknown values before this runs, but we keep this defensive in
     * case a caller bypasses the parser.
     */
    @JsonCreator
    public static CommandType fromString(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException(
                    "CommandEvent.command must not be null");
        }
        try {
            return CommandType.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException(
                    "Unknown command: " + raw
                            + " (supported: REPLAY, BULK_REPLAY, DELETE)");
        }
    }
}
