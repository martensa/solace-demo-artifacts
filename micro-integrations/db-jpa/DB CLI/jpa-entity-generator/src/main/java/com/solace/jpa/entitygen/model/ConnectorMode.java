package com.solace.jpa.entitygen.model;

/**
 * Defines the connector mode which determines what artifacts are generated.
 *
 * <ul>
 *   <li><b>SOURCE</b> — Read-only: Generates entities, repositories with strategy query methods, and DAOs
 *       with {@code findAllByRange} for the source connector. Views are included.</li>
 *   <li><b>SINK</b> — Write-only: Generates entities and minimal repositories (extending JpaRepository).
 *       No DAOs are generated. Views are excluded.</li>
 * </ul>
 */
public enum ConnectorMode {
    SOURCE,
    SINK
}
