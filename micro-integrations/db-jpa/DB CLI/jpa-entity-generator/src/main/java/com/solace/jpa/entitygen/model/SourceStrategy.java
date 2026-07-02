package com.solace.jpa.entitygen.model;

/**
 * Strategies for detecting data changes when using the source (read) connector.
 *
 * <ul>
 *   <li><b>READING_INDICATOR</b> - Tracks progress via a numeric column (e.g., auto-increment ID).
 *       Uses {@code GreaterThan} queries on the indicator column.</li>
 *   <li><b>TIMESTAMP</b> - Tracks progress via a timestamp column (e.g., updated_at).
 *       Uses date-range queries with {@code GreaterThanEqual} and {@code LessThan}.</li>
 *   <li><b>SEQUENTIAL</b> - Reads all records sequentially using pagination.
 *       No change detection; processes the entire table.</li>
 * </ul>
 */
public enum SourceStrategy {
    READING_INDICATOR,
    TIMESTAMP,
    SEQUENTIAL
}
