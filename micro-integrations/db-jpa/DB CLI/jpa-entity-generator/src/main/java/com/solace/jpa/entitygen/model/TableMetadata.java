package com.solace.jpa.entitygen.model;

import java.util.ArrayList;
import java.util.List;

/**
 * Complete metadata for a database table or view.
 */
public class TableMetadata {

    public enum TableType {
        TABLE,
        VIEW
    }

    private String tableName;
    private String schemaName;
    private String javaClassName;
    private TableType tableType;
    private String remarks;
    private List<ColumnMetadata> columns = new ArrayList<>();
    private List<ColumnMetadata> primaryKeys = new ArrayList<>();
    private List<RelationshipMetadata> importedRelationships = new ArrayList<>();  // FK in this table
    private List<RelationshipMetadata> exportedRelationships = new ArrayList<>();  // FK pointing to this table

    public String getTableName() {
        return tableName;
    }

    public void setTableName(String tableName) {
        this.tableName = tableName;
    }

    public String getSchemaName() {
        return schemaName;
    }

    public void setSchemaName(String schemaName) {
        this.schemaName = schemaName;
    }

    public String getJavaClassName() {
        return javaClassName;
    }

    public void setJavaClassName(String javaClassName) {
        this.javaClassName = javaClassName;
    }

    public TableType getTableType() {
        return tableType;
    }

    public void setTableType(TableType tableType) {
        this.tableType = tableType;
    }

    public String getRemarks() {
        return remarks;
    }

    public void setRemarks(String remarks) {
        this.remarks = remarks;
    }

    public List<ColumnMetadata> getColumns() {
        return columns;
    }

    public void setColumns(List<ColumnMetadata> columns) {
        this.columns = columns;
    }

    public List<ColumnMetadata> getPrimaryKeys() {
        return primaryKeys;
    }

    public void setPrimaryKeys(List<ColumnMetadata> primaryKeys) {
        this.primaryKeys = primaryKeys;
    }

    public List<RelationshipMetadata> getImportedRelationships() {
        return importedRelationships;
    }

    public void setImportedRelationships(List<RelationshipMetadata> importedRelationships) {
        this.importedRelationships = importedRelationships;
    }

    public List<RelationshipMetadata> getExportedRelationships() {
        return exportedRelationships;
    }

    public void setExportedRelationships(List<RelationshipMetadata> exportedRelationships) {
        this.exportedRelationships = exportedRelationships;
    }

    public boolean hasCompositePrimaryKey() {
        return primaryKeys.size() > 1;
    }

    public boolean isView() {
        return tableType == TableType.VIEW;
    }

    @Override
    public String toString() {
        return tableName + " (" + tableType + ", " + columns.size() + " columns, " +
                primaryKeys.size() + " PKs)";
    }
}
