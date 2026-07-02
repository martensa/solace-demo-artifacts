package com.solace.jpa.entitygen.cli;

import com.solace.jpa.entitygen.generator.*;
import com.solace.jpa.entitygen.model.*;
import com.solace.jpa.entitygen.schema.SchemaAnalyzer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.shell.standard.ShellComponent;
import org.springframework.shell.standard.ShellMethod;
import org.springframework.shell.standard.ShellOption;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.List;

/**
 * Spring Shell commands for the JPA Entity Generator CLI.
 */
@ShellComponent
public class GeneratorCommands {

    private static final Logger log = LoggerFactory.getLogger(GeneratorCommands.class);

    @ShellMethod(key = "generate", value = "Generate JPA entities, repositories, and DAOs from a database schema")
    public String generate(
            @ShellOption(value = "--vendor", help = "Database vendor: POSTGRESQL, MYSQL, ORACLE")
            String vendor,

            @ShellOption(value = "--url", help = "JDBC connection URL (e.g., jdbc:postgresql://localhost:5432/mydb)")
            String jdbcUrl,

            @ShellOption(value = "--username", help = "Database username")
            String username,

            @ShellOption(value = "--password", help = "Database password")
            String password,

            @ShellOption(value = "--schema", help = "Database schema name (e.g., public)")
            String schema,

            @ShellOption(value = "--package", help = "Base Java package for generated code (e.g., com.solace.connectors.database.sink)")
            String basePackage,

            @ShellOption(value = "--mode", help = "Connector mode: SOURCE or SINK")
            String mode,

            @ShellOption(value = "--strategy", help = "Source strategy: READING_INDICATOR, TIMESTAMP, SEQUENTIAL (SOURCE mode only)",
                    defaultValue = "SEQUENTIAL")
            String strategy,

            @ShellOption(value = "--strategy-column", help = "Column for reading-indicator or timestamp strategy (SOURCE mode only)",
                    defaultValue = ShellOption.NULL)
            String strategyColumn,

            @ShellOption(value = "--tables", help = "Comma-separated table names, or ALL for all tables",
                    defaultValue = "ALL")
            String tables,

            @ShellOption(value = "--include-views", help = "Whether to include database views (SOURCE mode only)",
                    defaultValue = "true")
            boolean includeViews,

            @ShellOption(value = "--views", help = "Comma-separated view names, or ALL for all views (SOURCE mode only)",
                    defaultValue = "ALL")
            String views,

            @ShellOption(value = "--output", help = "Output directory for generated source files",
                    defaultValue = "./generated-entities")
            String outputDir,

            @ShellOption(value = "--jar", help = "Path for the output JAR file",
                    defaultValue = ShellOption.NULL)
            String jarOutput,

            @ShellOption(value = "--relationships", help = "Generate @Transient relationship fields for child collections (SOURCE mode only)",
                    defaultValue = "true")
            boolean relationships,

            @ShellOption(value = "--dry-run", help = "Preview what will be generated without writing files",
                    defaultValue = "false")
            boolean dryRun,

            @ShellOption(value = "--clean", help = "Delete existing output directory before generating",
                    defaultValue = "false")
            boolean clean
    ) {
        try {
            // Build configuration
            GenerationConfig config = buildConfig(vendor, jdbcUrl, username, password, schema,
                    basePackage, mode, strategy, strategyColumn, tables, includeViews, views,
                    outputDir, relationships);

            // Validate
            String validationError = validateConfig(config);
            if (validationError != null) {
                return "ERROR: " + validationError;
            }

            return executeGeneration(config, jarOutput, dryRun, clean);

        } catch (Exception e) {
            log.error("Generation failed", e);
            return "ERROR: " + e.getMessage();
        }
    }

    @ShellMethod(key = "test-connection", value = "Test database connectivity")
    public String testConnection(
            @ShellOption(value = "--vendor", help = "Database vendor: POSTGRESQL, MYSQL, ORACLE")
            String vendor,

            @ShellOption(value = "--url", help = "JDBC connection URL")
            String jdbcUrl,

            @ShellOption(value = "--username", help = "Database username")
            String username,

            @ShellOption(value = "--password", help = "Database password")
            String password
    ) {
        try {
            DatabaseVendor dbVendor = DatabaseVendor.valueOf(vendor.toUpperCase());
            Class.forName(dbVendor.getDriverClass());

            java.sql.DriverManager.setLoginTimeout(15);
            try (var conn = java.sql.DriverManager.getConnection(jdbcUrl, username, password)) {
                var meta = conn.getMetaData();
                return String.format("Connection successful!\n  Product: %s %s\n  Driver: %s %s",
                        meta.getDatabaseProductName(), meta.getDatabaseProductVersion(),
                        meta.getDriverName(), meta.getDriverVersion());
            }
        } catch (Exception e) {
            return "Connection FAILED: " + e.getMessage();
        }
    }

    @ShellMethod(key = "list-tables", value = "List all tables and views in the database schema")
    public String listTables(
            @ShellOption(value = "--vendor", help = "Database vendor: POSTGRESQL, MYSQL, ORACLE")
            String vendor,

            @ShellOption(value = "--url", help = "JDBC connection URL")
            String jdbcUrl,

            @ShellOption(value = "--username", help = "Database username")
            String username,

            @ShellOption(value = "--password", help = "Database password")
            String password,

            @ShellOption(value = "--schema", help = "Database schema name")
            String schema
    ) {
        try {
            GenerationConfig config = new GenerationConfig();
            config.setVendor(DatabaseVendor.valueOf(vendor.toUpperCase()));
            config.setJdbcUrl(jdbcUrl);
            config.setUsername(username);
            config.setPassword(password);
            config.setSchema(schema);
            config.setBasePackage("temp");
            config.setIncludeViews(true);
            config.setGenerateRelationships(false);

            SchemaAnalyzer analyzer = new SchemaAnalyzer(config);
            List<TableMetadata> all = analyzer.analyze();

            StringBuilder sb = new StringBuilder();
            sb.append("\n=== Tables ===\n");
            long tableCount = all.stream().filter(t -> !t.isView()).count();
            sb.append("Found ").append(tableCount).append(" table(s):\n");
            all.stream().filter(t -> !t.isView()).forEach(t ->
                    sb.append("  - ").append(t.getTableName())
                      .append(" (").append(t.getColumns().size()).append(" columns")
                      .append(", ").append(t.getPrimaryKeys().size()).append(" PK(s))\n"));

            sb.append("\n=== Views ===\n");
            long viewCount = all.stream().filter(TableMetadata::isView).count();
            sb.append("Found ").append(viewCount).append(" view(s):\n");
            all.stream().filter(TableMetadata::isView).forEach(t ->
                    sb.append("  - ").append(t.getTableName())
                      .append(" (").append(t.getColumns().size()).append(" columns)\n"));

            return sb.toString();
        } catch (Exception e) {
            return "ERROR: " + e.getMessage();
        }
    }

    @ShellMethod(key = "describe-table", value = "Show detailed metadata for a specific table or view")
    public String describeTable(
            @ShellOption(value = "--vendor", help = "Database vendor: POSTGRESQL, MYSQL, ORACLE")
            String vendor,

            @ShellOption(value = "--url", help = "JDBC connection URL")
            String jdbcUrl,

            @ShellOption(value = "--username", help = "Database username")
            String username,

            @ShellOption(value = "--password", help = "Database password")
            String password,

            @ShellOption(value = "--schema", help = "Database schema name")
            String schema,

            @ShellOption(value = "--table", help = "Table or view name to describe")
            String tableName
    ) {
        try {
            // First pass: fetch the table metadata without relationships
            GenerationConfig config = new GenerationConfig();
            config.setVendor(DatabaseVendor.valueOf(vendor.toUpperCase()));
            config.setJdbcUrl(jdbcUrl);
            config.setUsername(username);
            config.setPassword(password);
            config.setSchema(schema);
            config.setBasePackage("temp");
            config.setTableNames(List.of(tableName));
            config.setIncludeViews(true);
            config.setViewNames(List.of(tableName));
            // Only fetch relationships for this specific table, not all tables
            config.setGenerateRelationships(true);

            SchemaAnalyzer analyzer = new SchemaAnalyzer(config);
            List<TableMetadata> tables = analyzer.analyze();

            if (tables.isEmpty()) {
                return "Table/view '" + tableName + "' not found in schema '" + schema + "'";
            }

            TableMetadata table = tables.get(0);
            StringBuilder sb = new StringBuilder();
            sb.append("\n=== ").append(table.getTableName()).append(" (")
              .append(table.getTableType()).append(") ===\n");
            if (table.getRemarks() != null) {
                sb.append("Description: ").append(table.getRemarks()).append("\n");
            }
            sb.append("Java class: ").append(table.getJavaClassName()).append("\n\n");

            sb.append("Columns:\n");
            sb.append(String.format("  %-30s %-20s %-20s %-8s %-5s %-5s\n",
                    "NAME", "SQL TYPE", "JAVA TYPE", "NULLABLE", "PK", "AUTO"));
            sb.append("  " + "-".repeat(100) + "\n");
            for (ColumnMetadata col : table.getColumns()) {
                sb.append(String.format("  %-30s %-20s %-20s %-8s %-5s %-5s\n",
                        col.getColumnName(),
                        col.getSqlTypeName(),
                        EntityGenerator.simpleType(col.getJavaTypeName()),
                        col.isNullable() ? "YES" : "NO",
                        col.isPrimaryKey() ? "YES" : "",
                        col.isAutoIncrement() ? "YES" : ""));
            }

            if (!table.getImportedRelationships().isEmpty()) {
                sb.append("\nForeign Keys (this table -> parent):\n");
                for (RelationshipMetadata rel : table.getImportedRelationships()) {
                    sb.append("  ").append(rel.getSourceColumn()).append(" -> ")
                      .append(rel.getTargetTable()).append(".").append(rel.getTargetColumn())
                      .append(rel.isCascadeDelete() ? " [CASCADE DELETE]" : "").append("\n");
                }
            }

            if (!table.getExportedRelationships().isEmpty()) {
                sb.append("\nReferenced By (child tables -> this table):\n");
                for (RelationshipMetadata rel : table.getExportedRelationships()) {
                    sb.append("  ").append(rel.getSourceTable()).append(".").append(rel.getSourceColumn())
                      .append(" -> ").append(rel.getTargetColumn())
                      .append(rel.isCascadeDelete() ? " [CASCADE DELETE]" : "").append("\n");
                }
            }

            return sb.toString();
        } catch (Exception e) {
            return "ERROR: " + e.getMessage();
        }
    }

    // ========================
    // Internal Methods
    // ========================

    private GenerationConfig buildConfig(String vendor, String jdbcUrl, String username,
                                          String password, String schema, String basePackage,
                                          String mode, String strategy, String strategyColumn,
                                          String tables, boolean includeViews, String views,
                                          String outputDir, boolean relationships) {
        GenerationConfig config = new GenerationConfig();
        config.setVendor(DatabaseVendor.valueOf(vendor.toUpperCase()));
        config.setJdbcUrl(jdbcUrl);
        config.setUsername(username);
        config.setPassword(password);
        config.setSchema(schema);
        config.setBasePackage(basePackage);
        config.setConnectorMode(ConnectorMode.valueOf(mode.toUpperCase()));
        config.setOutputDirectory(outputDir);

        // Source-specific settings (ignored for SINK mode)
        if (config.isSourceMode()) {
            config.setSourceStrategy(SourceStrategy.valueOf(strategy.toUpperCase()));
            config.setStrategyColumn(strategyColumn);
            config.setIncludeViews(includeViews);
            config.setGenerateRelationships(relationships);

            // Parse view selection
            if (!"ALL".equalsIgnoreCase(views)) {
                config.setViewNames(Arrays.stream(views.split(","))
                        .map(String::trim)
                        .filter(s -> !s.isEmpty())
                        .toList());
            }
        } else {
            // SINK mode: no views, no relationships, no strategy
            config.setIncludeViews(false);
            config.setGenerateRelationships(false);
        }

        // Parse table selection
        if (!"ALL".equalsIgnoreCase(tables)) {
            config.setTableNames(Arrays.stream(tables.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .toList());
        }

        return config;
    }

    private String validateConfig(GenerationConfig config) {
        if (config.getVendor() == null) return "Database vendor is required";
        if (config.getJdbcUrl() == null || config.getJdbcUrl().isBlank()) return "JDBC URL is required";
        if (config.getUsername() == null || config.getUsername().isBlank()) return "Username is required";
        if (config.getSchema() == null || config.getSchema().isBlank()) return "Schema is required";
        if (config.getBasePackage() == null || config.getBasePackage().isBlank()) return "Base package is required";
        if (config.getConnectorMode() == null) return "Connector mode (--mode SOURCE or SINK) is required";

        if (config.requiresStrategyColumn() &&
                (config.getStrategyColumn() == null || config.getStrategyColumn().isBlank())) {
            return "Strategy column (--strategy-column) is required for " +
                    config.getSourceStrategy() + " strategy";
        }

        return null;
    }

    private String executeGeneration(GenerationConfig config, String jarOutput,
                                      boolean dryRun, boolean clean) throws SQLException, IOException {
        StringBuilder result = new StringBuilder();
        result.append("\n========================================\n");
        result.append("  JPA Entity Generator");
        if (dryRun) result.append("  [DRY RUN]");
        result.append("\n========================================\n\n");

        // Step 1: Analyze schema
        result.append("[1/4] Analyzing database schema...\n");
        SchemaAnalyzer analyzer = new SchemaAnalyzer(config);
        List<TableMetadata> tables = analyzer.analyze();

        if (tables.isEmpty()) {
            return result.append("No tables or views found matching the criteria.").toString();
        }

        long tableCount = tables.stream().filter(t -> !t.isView()).count();
        long viewCount = tables.stream().filter(TableMetadata::isView).count();
        result.append("  Found ").append(tableCount).append(" table(s)");
        if (config.isSourceMode() && viewCount > 0) {
            result.append(" and ").append(viewCount).append(" view(s)");
        }
        result.append("\n\n");

        // Validate strategy column exists in at least one table (SOURCE mode only)
        if (config.requiresStrategyColumn()) {
            String stratCol = config.getStrategyColumn();
            boolean columnFound = tables.stream()
                    .filter(t -> !t.isView())
                    .anyMatch(t -> t.getColumns().stream()
                            .anyMatch(c -> c.getColumnName().equalsIgnoreCase(stratCol)));
            if (!columnFound) {
                List<String> availableColumns = tables.stream()
                        .filter(t -> !t.isView())
                        .flatMap(t -> t.getColumns().stream())
                        .map(c -> c.getColumnName())
                        .distinct()
                        .sorted()
                        .toList();
                return result.append("ERROR: Strategy column '").append(stratCol)
                        .append("' not found in any table.\n  Available columns: ")
                        .append(String.join(", ", availableColumns)).toString();
            }
        }

        // Compute planned artifacts
        Path outputDir = Path.of(config.getOutputDirectory());
        long compositeCount = tables.stream().filter(TableMetadata::hasCompositePrimaryKey).count();

        // --- Dry-run: preview planned output without writing ---
        if (dryRun) {
            result.append("[DRY RUN] No files will be written.\n\n");
            result.append("Planned output directory: ").append(outputDir.toAbsolutePath()).append("\n");
            result.append("Package: ").append(config.getBasePackage()).append(".entity\n");
            result.append("Mode: ").append(config.getConnectorMode()).append("\n");
            if (config.isSourceMode()) {
                result.append("Strategy: ").append(config.getSourceStrategy()).append("\n");
                if (config.getStrategyColumn() != null) {
                    result.append("Strategy Column: ").append(config.getStrategyColumn()).append("\n");
                }
            }
            result.append("\nPlanned artifacts:\n");
            int fileCount = 0;
            for (TableMetadata table : tables) {
                result.append("  ").append(table.getTableName()).append(": ")
                      .append(table.getJavaClassName()).append(".java");
                fileCount++;
                if (table.hasCompositePrimaryKey()) {
                    result.append(", ").append(table.getJavaClassName()).append("Id.java");
                    fileCount++;
                }
                result.append(", ").append(table.getJavaClassName()).append("Repo.java");
                fileCount++;
                if (config.isSourceMode()) {
                    result.append(", ").append(table.getJavaClassName()).append("DAO.java");
                    fileCount++;
                }
                result.append("\n");
            }
            result.append("\nTotal: ").append(fileCount).append(" file(s) would be generated.\n");
            if (jarOutput != null && !jarOutput.isBlank()) {
                result.append("JAR would be created at: ").append(jarOutput).append("\n");
            }
            return result.toString();
        }

        // --- Clean: remove existing output directory before generating ---
        if (clean && Files.exists(outputDir)) {
            deleteDirectory(outputDir);
            result.append("[CLEAN] Deleted existing output directory: ")
                  .append(outputDir.toAbsolutePath()).append("\n\n");
        }

        // Step 2: Generate entities
        result.append("[2/4] Generating JPA entities...\n");
        EntityGenerator entityGen = new EntityGenerator(config);
        entityGen.generate(tables, outputDir);
        result.append("  Generated ").append(tables.size()).append(" entity class(es)\n");
        if (compositeCount > 0) {
            result.append("  Generated ").append(compositeCount).append(" composite key class(es)\n");
        }
        result.append("\n");

        // Step 3: Generate repositories (always) and DAOs (SOURCE mode only)
        result.append("[3/4] Generating repositories");
        if (config.isSourceMode()) result.append(" and DAOs");
        result.append("...\n");

        RepositoryGenerator repoGen = new RepositoryGenerator(config);
        repoGen.generate(tables, outputDir);
        result.append("  Generated ").append(tables.size()).append(" repository interface(s)\n");

        if (config.isSourceMode()) {
            DaoGenerator daoGen = new DaoGenerator(config);
            daoGen.generate(tables, outputDir);
            result.append("  Generated ").append(tables.size()).append(" DAO class(es)\n");
        }
        result.append("\n");

        // Step 4: Package JAR
        if (jarOutput != null && !jarOutput.isBlank()) {
            result.append("[4/4] Packaging JAR...\n");
            JarPackager packager = new JarPackager();
            packager.packageJar(outputDir, Path.of(jarOutput), config.getBasePackage());
            result.append("  JAR created: ").append(jarOutput).append("\n\n");
        } else {
            result.append("[4/4] Skipping JAR packaging (no --jar option specified)\n\n");
        }

        // Summary
        result.append("========================================\n");
        result.append("  Generation Complete!\n");
        result.append("========================================\n");
        result.append("  Output directory: ").append(outputDir.toAbsolutePath()).append("\n");
        result.append("  Package: ").append(config.getBasePackage()).append(".entity\n");
        result.append("  Mode: ").append(config.getConnectorMode()).append("\n");
        if (config.isSourceMode()) {
            result.append("  Strategy: ").append(config.getSourceStrategy()).append("\n");
            if (config.getStrategyColumn() != null) {
                result.append("  Strategy Column: ").append(config.getStrategyColumn()).append("\n");
            }
        }
        result.append("\n  Generated artifacts per table/view:\n");
        for (TableMetadata table : tables) {
            result.append("    ").append(table.getTableName()).append(": ")
                  .append(table.getJavaClassName()).append(".java");
            if (table.hasCompositePrimaryKey()) {
                result.append(", ").append(table.getJavaClassName()).append("Id.java");
            }
            result.append(", ").append(table.getJavaClassName()).append("Repo.java");
            if (config.isSourceMode()) {
                result.append(", ").append(table.getJavaClassName()).append("DAO.java");
            }
            result.append("\n");
        }

        return result.toString();
    }

    /**
     * Recursively deletes a directory and all its contents.
     */
    private void deleteDirectory(Path dir) throws IOException {
        if (!Files.exists(dir)) return;
        Files.walkFileTree(dir, new java.nio.file.SimpleFileVisitor<>() {
            @Override
            public java.nio.file.FileVisitResult visitFile(Path file,
                    java.nio.file.attribute.BasicFileAttributes attrs) throws IOException {
                Files.delete(file);
                return java.nio.file.FileVisitResult.CONTINUE;
            }
            @Override
            public java.nio.file.FileVisitResult postVisitDirectory(Path d, IOException exc) throws IOException {
                if (exc != null) throw exc;
                Files.delete(d);
                return java.nio.file.FileVisitResult.CONTINUE;
            }
        });
    }
}
