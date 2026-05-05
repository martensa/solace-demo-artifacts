package com.solace.labs.mi.topiccompaction.replay;

import java.util.regex.Pattern;

/**
 * Matches Solace topic-style patterns against concrete topic strings,
 * with two practical optimisations:
 * <ul>
 *   <li>A {@link #prefixForRocksDb() rocksdb-prefix} is computed for
 *       use as the start of an iterator scan; it is the longest
 *       prefix containing no wildcard.</li>
 *   <li>The pattern is compiled to a {@link Pattern} once at
 *       construction.</li>
 * </ul>
 *
 * <p>Solace wildcard semantics implemented here:
 * <ul>
 *   <li>{@code *} matches exactly one topic level (no slashes)</li>
 *   <li>{@code &gt;} matches the remainder of the topic (one or more
 *       additional levels). May only appear as the final character.</li>
 *   <li>Other characters match literally.</li>
 * </ul>
 *
 * <p>Examples:
 * <ul>
 *   <li>{@code orders/created/*} matches {@code orders/created/A}
 *       but not {@code orders/created/A/B}</li>
 *   <li>{@code orders/&gt;} matches {@code orders/created/A} and
 *       {@code orders/created/A/B}</li>
 *   <li>{@code &gt;} matches every key in the store</li>
 *   <li>{@code orders/created/A} (no wildcards) only matches that
 *       exact key</li>
 * </ul>
 *
 * <p>This implementation is thread-safe: the compiled {@link Pattern}
 * and the prefix string are immutable.
 */
public final class SolacePatternMatcher {

    private final String pattern;
    private final Pattern regex;
    private final String prefixForRocksDb;

    public SolacePatternMatcher(String pattern) {
        if (pattern == null || pattern.isEmpty()) {
            throw new IllegalArgumentException(
                    "pattern must not be null or empty");
        }
        if (pattern.indexOf('>') >= 0
                && pattern.indexOf('>') != pattern.length() - 1) {
            throw new IllegalArgumentException(
                    "'>' wildcard may only appear at end of pattern");
        }
        this.pattern = pattern;
        this.prefixForRocksDb = computePrefix(pattern);
        this.regex = Pattern.compile(toRegex(pattern));
    }

    /**
     * @return the pattern portion up to the first wildcard, suitable
     *         as a prefix-iterator seek key. Empty string for the
     *         {@code &gt;} pattern (full scan).
     */
    public String prefixForRocksDb() {
        return prefixForRocksDb;
    }

    public boolean matches(String key) {
        return key != null && regex.matcher(key).matches();
    }

    @Override
    public String toString() {
        return "SolacePatternMatcher[" + pattern + "]";
    }

    private static String computePrefix(String pattern) {
        for (int i = 0; i < pattern.length(); i++) {
            char c = pattern.charAt(i);
            if (c == '*' || c == '>') {
                return pattern.substring(0, i);
            }
        }
        return pattern;
    }

    private static String toRegex(String pattern) {
        StringBuilder sb = new StringBuilder("^");
        int len = pattern.length();
        for (int i = 0; i < len; i++) {
            char c = pattern.charAt(i);
            switch (c) {
                case '>':
                    // Must be the last character (validated above).
                    // '>' matches "the rest of the topic", which is
                    // one or more additional levels separated by /.
                    // It does not match an empty string.
                    sb.append(".+");
                    break;
                case '*':
                    // Single-level wildcard: any non-slash chars.
                    sb.append("[^/]+");
                    break;
                case '.':
                case '+':
                case '(':
                case ')':
                case '[':
                case ']':
                case '{':
                case '}':
                case '\\':
                case '^':
                case '$':
                case '|':
                case '?':
                    sb.append('\\').append(c);
                    break;
                default:
                    sb.append(c);
            }
        }
        sb.append('$');
        return sb.toString();
    }
}
