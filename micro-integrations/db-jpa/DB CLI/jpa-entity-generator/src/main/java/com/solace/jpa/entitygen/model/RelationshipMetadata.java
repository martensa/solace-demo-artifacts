package com.solace.jpa.entitygen.model;

/**
 * Represents a foreign key relationship between two tables.
 */
public class RelationshipMetadata {

    public enum RelationType {
        MANY_TO_ONE,
        ONE_TO_MANY
    }

    private String constraintName;
    private String sourceTable;
    private String sourceColumn;
    private String targetTable;
    private String targetColumn;
    private RelationType relationType;
    private boolean cascadeDelete;

    public String getConstraintName() {
        return constraintName;
    }

    public void setConstraintName(String constraintName) {
        this.constraintName = constraintName;
    }

    public String getSourceTable() {
        return sourceTable;
    }

    public void setSourceTable(String sourceTable) {
        this.sourceTable = sourceTable;
    }

    public String getSourceColumn() {
        return sourceColumn;
    }

    public void setSourceColumn(String sourceColumn) {
        this.sourceColumn = sourceColumn;
    }

    public String getTargetTable() {
        return targetTable;
    }

    public void setTargetTable(String targetTable) {
        this.targetTable = targetTable;
    }

    public String getTargetColumn() {
        return targetColumn;
    }

    public void setTargetColumn(String targetColumn) {
        this.targetColumn = targetColumn;
    }

    public RelationType getRelationType() {
        return relationType;
    }

    public void setRelationType(RelationType relationType) {
        this.relationType = relationType;
    }

    public boolean isCascadeDelete() {
        return cascadeDelete;
    }

    public void setCascadeDelete(boolean cascadeDelete) {
        this.cascadeDelete = cascadeDelete;
    }

    @Override
    public String toString() {
        return sourceTable + "." + sourceColumn + " -> " + targetTable + "." + targetColumn +
                " (" + relationType + ")";
    }
}
