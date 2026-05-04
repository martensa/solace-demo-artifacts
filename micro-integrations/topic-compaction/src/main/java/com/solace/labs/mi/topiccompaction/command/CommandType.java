package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.annotation.JsonCreator;

/**
 * Set of accepted command verbs. V1 ships only {@link #REPLAY};
 * the enum exists from day one to make extension obvious.
 */
public enum CommandType {
    REPLAY,
    DELETE,        // V2 - reserved
    BULK_REPLAY;   // V2 - reserved

    /**
     * Case-insensitive parse so callers can write {@code "replay"} or
     * {@code "Replay"} without surprises.
     */
    @JsonCreator
    public static CommandType fromString(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("CommandEvent.command must not be null");
        }
        try {
            return CommandType.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("Unknown command: " + raw + " (supported: REPLAY)");
        }
    }
}
