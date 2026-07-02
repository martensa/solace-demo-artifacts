package com.solace.jpa.entitygen.generator;

import com.solace.jpa.entitygen.model.*;
import com.solace.jpa.entitygen.schema.SchemaAnalyzer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

/**
 * Generates DAO (Data Access Object) classes that wrap Repository calls.
 * DAOs are only generated in SOURCE mode and provide:
 * <ul>
 *   <li>{@code findAllByRange(PageRequest/Sort/Pageable, String[])} — strategy-specific record fetching</li>
 *   <li>{@code findAll()} — convenience method for fetching all records</li>
 * </ul>
 */
public class DaoGenerator {

    private static final Logger log = LoggerFactory.getLogger(DaoGenerator.class);

    private final GenerationConfig config;

    public DaoGenerator(GenerationConfig config) {
        this.config = config;
    }

    public void generate(List<TableMetadata> tables, Path outputDir) throws IOException {
        String entityPackage = config.getBasePackage() + ".entity";
        Path packageDir = outputDir.resolve(entityPackage.replace('.', '/'));
        Files.createDirectories(packageDir);

        for (TableMetadata table : tables) {
            String source = generateDaoSource(table, entityPackage);
            Path file = packageDir.resolve(table.getJavaClassName() + "DAO.java");
            Files.writeString(file, source);
            log.info("Generated DAO: {}", file.getFileName());
        }
    }

    private String generateDaoSource(TableMetadata table, String entityPackage) {
        StringBuilder sb = new StringBuilder();
        String className = table.getJavaClassName();
        String daoName = className + "DAO";
        String repoName = className + "Repo";

        // File header
        sb.append(EntityGenerator.fileHeader(table.getTableName(), table.getSchemaName()));

        // Package
        sb.append("package ").append(entityPackage).append(";\n\n");

        // Imports
        Set<String> imports = new TreeSet<>();
        imports.add("org.springframework.stereotype.Component");
        imports.add("jakarta.annotation.Resource");
        imports.add("java.util.List");
        imports.add("org.springframework.data.domain.PageRequest");
        imports.add("org.springframework.data.domain.Pageable");
        imports.add("org.springframework.data.domain.Sort");

        addStrategyImports(imports, table);

        imports.stream().sorted().forEach(imp -> sb.append("import ").append(imp).append(";\n"));
        sb.append("\n");

        // Class
        sb.append("@Component\n");
        sb.append("public class ").append(daoName).append(" {\n\n");

        // Repository injection via @Resource
        sb.append("    @Resource\n");
        sb.append("    ").append(repoName).append(" repo;\n\n");

        // Source methods (strategy-specific)
        generateSourceDaoMethods(sb, table, className);

        sb.append("}\n");
        return sb.toString();
    }

    private void generateSourceDaoMethods(StringBuilder sb, TableMetadata table, String className) {
        SourceStrategy strategy = config.getSourceStrategy();
        if (strategy == null) strategy = SourceStrategy.SEQUENTIAL;

        String strategyCol = config.getStrategyColumn();

        switch (strategy) {
            case READING_INDICATOR -> {
                if (strategyCol == null || strategyCol.isEmpty()) {
                    // Fall back to sequential if no strategy column provided
                    sb.append("    /**\n");
                    sb.append("     * Sequential fallback: no strategy column configured.\n");
                    sb.append("     */\n");
                    sb.append("    public List<").append(className)
                      .append("> findAllByRange(PageRequest pageable, String[] values) {\n");
                    sb.append("        return repo.findAll(pageable).getContent();\n");
                    sb.append("    }\n\n");
                    break;
                }
                String colType = resolveStrategyColumnType(table, strategyCol);
                String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                // For @EmbeddedId, PK columns are accessed via id.field path
                if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                    colField = "Id" + colField;
                }

                sb.append("    /**\n");
                sb.append("     * Reading Indicator: fetch records where ").append(strategyCol)
                  .append(" > lastValue.\n");
                sb.append("     * @param pageable pagination configuration\n");
                sb.append("     * @param values   values[0] = last processed indicator value\n");
                sb.append("     */\n");
                sb.append("    public List<").append(className)
                  .append("> findAllByRange(PageRequest pageable, String[] values) {\n");
                sb.append("        return repo.find").append(className).append("By")
                  .append(colField).append("GreaterThan(");
                sb.append(parseExpression(colType, "values[0]")).append(", pageable);\n");
                sb.append("    }\n\n");
            }
            case TIMESTAMP -> {
                if (strategyCol == null || strategyCol.isEmpty()) {
                    sb.append("    /**\n");
                    sb.append("     * Sequential fallback: no strategy column configured.\n");
                    sb.append("     */\n");
                    sb.append("    public List<").append(className)
                      .append("> findAllByRange(PageRequest pageable, String[] values) {\n");
                    sb.append("        return repo.findAll(pageable).getContent();\n");
                    sb.append("    }\n\n");
                    break;
                }
                String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                // For @EmbeddedId, PK columns are accessed via id.field path
                if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                    colField = "Id" + colField;
                }
                String colFqn = resolveStrategyColumnFqn(table, strategyCol);
                String colType = EntityGenerator.simpleType(colFqn);
                String parseFrom = timestampParseExpression(colFqn, "values[0]");
                String parseTo = timestampParseExpression(colFqn, "values[1]");

                sb.append("    /**\n");
                sb.append("     * Timestamp: fetch records where ").append(strategyCol)
                  .append(" is within [from, to) window.\n");
                sb.append("     * @param sort   sort configuration\n");
                sb.append("     * @param values values[0] = from timestamp, values[1] = to timestamp\n");
                sb.append("     */\n");
                sb.append("    public List<").append(className)
                  .append("> findAllByRange(Sort sort, String[] values) {\n");
                sb.append("        return repo.find").append(className).append("By")
                  .append(colField).append("GreaterThanEqualAnd")
                  .append(colField).append("LessThan(\n");
                sb.append("                ").append(parseFrom).append(",\n");
                sb.append("                ").append(parseTo).append(", sort);\n");
                sb.append("    }\n\n");

                sb.append("    /**\n");
                sb.append("     * Timestamp: fetch records with pagination.\n");
                sb.append("     */\n");
                sb.append("    public List<").append(className)
                  .append("> findAllByRange(Pageable page, String[] values) {\n");
                sb.append("        return repo.find").append(className).append("By")
                  .append(colField).append("GreaterThanEqualAnd")
                  .append(colField).append("LessThan(\n");
                sb.append("                ").append(parseFrom).append(",\n");
                sb.append("                ").append(parseTo).append(", page);\n");
                sb.append("    }\n\n");
            }
            case SEQUENTIAL -> {
                if (strategyCol != null && !strategyCol.isEmpty()) {
                    String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                    if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                        colField = "Id" + colField;
                    }
                    sb.append("    /**\n");
                    sb.append("     * Sequential: fetch records where ").append(strategyCol)
                      .append(" > lastValue.\n");
                    sb.append("     */\n");
                    sb.append("    public List<").append(className)
                      .append("> findAllByRange(PageRequest pageable, String[] values) {\n");
                    sb.append("        return repo.find").append(className).append("By")
                      .append(colField).append("GreaterThan(new java.math.BigDecimal(values[0]), pageable);\n");
                    sb.append("    }\n\n");
                } else {
                    sb.append("    /**\n");
                    sb.append("     * Sequential: fetch all records with pagination.\n");
                    sb.append("     */\n");
                    sb.append("    public List<").append(className)
                      .append("> findAllByRange(PageRequest pageable, String[] values) {\n");
                    sb.append("        return repo.findAll(pageable).getContent();\n");
                    sb.append("    }\n\n");
                }
            }
        }

        // findAll convenience
        sb.append("    /**\n");
        sb.append("     * Fetch all records (use with caution on large tables).\n");
        sb.append("     */\n");
        sb.append("    public List<").append(className).append("> findAll() {\n");
        sb.append("        return repo.findAll();\n");
        sb.append("    }\n\n");
    }

    private void addStrategyImports(Set<String> imports, TableMetadata table) {
        SourceStrategy strategy = config.getSourceStrategy();
        String strategyCol = config.getStrategyColumn();
        if (strategy == SourceStrategy.READING_INDICATOR && strategyCol != null) {
            String colType = resolveStrategyColumnType(table, strategyCol);
            if ("BigDecimal".equals(colType)) imports.add("java.math.BigDecimal");
        }
        if (strategy == SourceStrategy.TIMESTAMP && strategyCol != null) {
            imports.add("java.util.Date");
        }
        if (strategy == SourceStrategy.SEQUENTIAL && strategyCol != null) {
            imports.add("java.math.BigDecimal");
        }
    }

    private String resolveStrategyColumnType(TableMetadata table, String columnName) {
        if (columnName == null) return "Object";
        return table.getColumns().stream()
                .filter(c -> c.getColumnName().equalsIgnoreCase(columnName))
                .findFirst()
                .map(c -> EntityGenerator.simpleType(c.getJavaTypeName()))
                .orElse("Object");
    }

    /**
     * Returns the fully-qualified Java type of a strategy column.
     */
    private String resolveStrategyColumnFqn(TableMetadata table, String columnName) {
        if (columnName == null) return "java.lang.Object";
        return table.getColumns().stream()
                .filter(c -> c.getColumnName().equalsIgnoreCase(columnName))
                .findFirst()
                .map(ColumnMetadata::getJavaTypeName)
                .orElse("java.lang.Object");
    }

    private boolean isPrimaryKeyColumn(TableMetadata table, String columnName) {
        return table.getPrimaryKeys().stream()
                .anyMatch(pk -> pk.getColumnName().equalsIgnoreCase(columnName));
    }

    /**
     * Generates a parsing expression to convert a String value to the target type.
     */
    private String parseExpression(String type, String valueExpr) {
        return switch (type) {
            case "Integer" -> "Integer.parseInt(" + valueExpr + ")";
            case "Long" -> "Long.parseLong(" + valueExpr + ")";
            case "Short" -> "Short.parseShort(" + valueExpr + ")";
            case "BigDecimal" -> "new java.math.BigDecimal(" + valueExpr + ")";
            case "Double" -> "Double.parseDouble(" + valueExpr + ")";
            case "Float" -> "Float.parseFloat(" + valueExpr + ")";
            default -> valueExpr;
        };
    }

    /**
     * Generates a parsing expression to convert a String value to the appropriate
     * temporal type based on the actual strategy column's Java type.
     * This ensures type compatibility with the entity field (e.g., LocalDateTime, OffsetDateTime).
     */
    private String timestampParseExpression(String fqnType, String valueExpr) {
        // Connector runtime always passes epoch millis as String — always use java.util.Date
        return "new java.util.Date(Long.parseLong(" + valueExpr + "))";
    }
}
