package com.solace.jpa.entitygen;

import com.solace.jpa.entitygen.schema.SchemaAnalyzer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for SchemaAnalyzer naming utilities (toClassName, toFieldName, capitalize).
 */
class SchemaAnalyzerNamingTest {

    // ========================
    // toClassName
    // ========================

    @ParameterizedTest
    @CsvSource({
            "order_items,     OrderItems",
            "USER,            User",
            "product,         Product",
            "my_table_name,   MyTableName",
            "UPPER_CASE,      UpperCase",
            "single,          Single",
    })
    void toClassNameConvertsSnakeCaseToPascalCase(String input, String expected) {
        assertEquals(expected, SchemaAnalyzer.toClassName(input));
    }

    @Test
    void toClassNameHandlesNullInput() {
        assertEquals("UnnamedTable", SchemaAnalyzer.toClassName(null));
    }

    @Test
    void toClassNameHandlesBlankInput() {
        assertEquals("UnnamedTable", SchemaAnalyzer.toClassName("  "));
    }

    @Test
    void toClassNamePrefixesNumericStart() {
        String result = SchemaAnalyzer.toClassName("123table");
        assertTrue(result.startsWith("T"), "Should prefix with T for numeric start: " + result);
    }

    // ========================
    // toFieldName
    // ========================

    @ParameterizedTest
    @CsvSource({
            "order_date,      orderDate",
            "USER_ID,         userId",
            "product_name,    productName",
            "ID,              id",
    })
    void toFieldNameConvertsSnakeCaseToCamelCase(String input, String expected) {
        assertEquals(expected, SchemaAnalyzer.toFieldName(input));
    }

    @Test
    void toFieldNameEscapesJavaReservedKeywords() {
        assertEquals("class_", SchemaAnalyzer.toFieldName("class"));
        assertEquals("return_", SchemaAnalyzer.toFieldName("return"));
        assertEquals("int_", SchemaAnalyzer.toFieldName("int"));
        assertEquals("new_", SchemaAnalyzer.toFieldName("new"));
        assertEquals("public_", SchemaAnalyzer.toFieldName("public"));
    }

    @Test
    void toFieldNameDoesNotEscapeNonKeywords() {
        assertEquals("name", SchemaAnalyzer.toFieldName("name"));
        assertEquals("value", SchemaAnalyzer.toFieldName("value"));
        assertEquals("status", SchemaAnalyzer.toFieldName("status"));
    }

    @Test
    void toFieldNameHandlesNullInput() {
        assertEquals("unnamed", SchemaAnalyzer.toFieldName(null));
    }

    // ========================
    // capitalize
    // ========================

    @Test
    void capitalizeConvertsFirstCharToUpper() {
        assertEquals("OrderDate", SchemaAnalyzer.capitalize("orderDate"));
        assertEquals("Id", SchemaAnalyzer.capitalize("id"));
    }

    @Test
    void capitalizeHandlesNull() {
        assertNull(SchemaAnalyzer.capitalize(null));
    }

    @Test
    void capitalizeHandlesEmpty() {
        assertEquals("", SchemaAnalyzer.capitalize(""));
    }
}
