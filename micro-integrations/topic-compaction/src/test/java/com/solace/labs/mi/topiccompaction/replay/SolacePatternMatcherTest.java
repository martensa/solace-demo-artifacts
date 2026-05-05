package com.solace.labs.mi.topiccompaction.replay;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SolacePatternMatcherTest {

    @Test
    void exactPatternMatchesOnlyExactKey() {
        SolacePatternMatcher m = new SolacePatternMatcher(
                "orders/created/A");
        assertThat(m.matches("orders/created/A")).isTrue();
        assertThat(m.matches("orders/created/B")).isFalse();
        assertThat(m.matches("orders/created/A/B")).isFalse();
        assertThat(m.matches("orders/created/")).isFalse();
        assertThat(m.prefixForRocksDb()).isEqualTo("orders/created/A");
    }

    @Test
    void singleLevelWildcardMatchesOneSegment() {
        SolacePatternMatcher m = new SolacePatternMatcher(
                "orders/created/*");
        assertThat(m.matches("orders/created/A")).isTrue();
        assertThat(m.matches("orders/created/12345")).isTrue();
        assertThat(m.matches("orders/created/A/B")).isFalse();
        assertThat(m.matches("orders/created/")).isFalse();
        assertThat(m.matches("orders/updated/A")).isFalse();
        assertThat(m.prefixForRocksDb()).isEqualTo("orders/created/");
    }

    @Test
    void multiLevelWildcardMatchesRemainder() {
        SolacePatternMatcher m = new SolacePatternMatcher("orders/>");
        assertThat(m.matches("orders/created/A")).isTrue();
        assertThat(m.matches("orders/created/A/B/C")).isTrue();
        assertThat(m.matches("orders/")).isFalse();
        assertThat(m.matches("orders")).isFalse();
        assertThat(m.matches("invoices/A")).isFalse();
        assertThat(m.prefixForRocksDb()).isEqualTo("orders/");
    }

    @Test
    void rootMultiLevelMatchesEverything() {
        SolacePatternMatcher m = new SolacePatternMatcher(">");
        assertThat(m.matches("a")).isTrue();
        assertThat(m.matches("a/b/c/d")).isTrue();
        assertThat(m.prefixForRocksDb()).isEmpty();
    }

    @Test
    void mixedWildcardsWork() {
        SolacePatternMatcher m = new SolacePatternMatcher(
                "orders/*/A/>");
        assertThat(m.matches("orders/created/A/B")).isTrue();
        assertThat(m.matches("orders/updated/A/X/Y")).isTrue();
        assertThat(m.matches("orders/created/A")).isFalse();
        assertThat(m.matches("orders/created/B/X")).isFalse();
        assertThat(m.prefixForRocksDb()).isEqualTo("orders/");
    }

    @Test
    void regexSpecialCharsInPatternAreEscaped() {
        SolacePatternMatcher m = new SolacePatternMatcher(
                "ord.ers/+/(/x");
        // None of . + ( should be interpreted as regex.
        assertThat(m.matches("ord.ers/+/(/x")).isTrue();
        assertThat(m.matches("ordXers/+/(/x")).isFalse();
    }

    @Test
    void rejectsMidstringMultiLevelWildcard() {
        assertThatThrownBy(() ->
                new SolacePatternMatcher("orders/>/created"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("'>'");
    }

    @Test
    void rejectsNullAndEmpty() {
        assertThatThrownBy(() -> new SolacePatternMatcher(null))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new SolacePatternMatcher(""))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
