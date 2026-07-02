/**
 * Sanitize Entity Relationships
 *
 * Removes dangling JPA relationship references from Hibernate-generated
 * entity Java files when the referenced entity class is not present in
 * the same directory.
 *
 * This fixes Maven compilation failures caused by the entity filtering
 * in updateEntityFiles(), which deletes entity files for unselected tables
 * but does not clean up @OneToMany / @ManyToOne / @ManyToMany / @OneToOne
 * references in the remaining files.
 *
 * What it removes for each missing referenced type:
 *   1. Field declarations        (e.g. `private Set<Orders> orderses = ...;`)
 *   2. Constructor parameters    (e.g. `, Set<Orders> orderses`)
 *   3. Constructor body lines    (e.g. `this.orderses = orderses;`)
 *   4. Relationship annotations  (e.g. `@OneToMany(...)`, `@ManyToOne(...)`, `@JoinColumn(...)`)
 *   5. Getter/setter methods     (e.g. `getOrderses()` / `setOrderses(...)`)
 *   6. Now-unused imports        (e.g. `import jakarta.persistence.OneToMany;`)
 */

const fs = require('fs');
const path = require('path');

/**
 * Scans a directory of .java entity files and removes references to
 * entity types whose .java files are not present in the directory.
 *
 * @param {string} entityDir - Path to the directory containing entity .java files
 * @returns {{ sanitizedFiles: string[], removedReferences: Object }} Summary of changes
 */
function sanitizeEntityRelationships(entityDir) {
    if (!fs.existsSync(entityDir)) {
        console.log(`[Sanitize] Directory does not exist: ${entityDir}`);
        return { sanitizedFiles: [], removedReferences: {} };
    }

    // Build the set of entity class names that ARE present
    const javaFiles = fs.readdirSync(entityDir).filter(f => f.endsWith('.java'));
    const presentTypes = new Set(javaFiles.map(f => f.replace('.java', '')));

    // Also include standard Java/JPA types that are not entity references
    const standardTypes = new Set([
        'String', 'Integer', 'Long', 'Double', 'Float', 'Boolean',
        'BigDecimal', 'BigInteger', 'Date', 'Timestamp', 'LocalDate',
        'LocalDateTime', 'Instant', 'UUID', 'Byte', 'Short', 'Character',
        'Object', 'Number', 'Comparable', 'Serializable',
        'Set', 'List', 'Map', 'Collection', 'HashSet', 'ArrayList',
        'HashMap', 'LinkedList', 'TreeSet', 'TreeMap',
    ]);

    const sanitizedFiles = [];
    const removedReferences = {};

    for (const javaFile of javaFiles) {
        // Skip DAO, Repo, and Id files — only process entity files
        if (javaFile.includes('DAO') || javaFile.includes('Repo')) {
            continue;
        }

        const filePath = path.join(entityDir, javaFile);
        const originalContent = fs.readFileSync(filePath, 'utf-8');

        // Find all referenced types that are NOT present and NOT standard
        const missingTypes = findMissingReferencedTypes(originalContent, presentTypes, standardTypes);

        if (missingTypes.length === 0) {
            continue;
        }

        console.log(`[Sanitize] ${javaFile}: removing references to missing types: ${missingTypes.join(', ')}`);

        let sanitized = originalContent;
        for (const missingType of missingTypes) {
            sanitized = removeTypeReferences(sanitized, missingType);
        }

        // Clean up imports that are no longer needed
        sanitized = cleanupUnusedImports(sanitized);

        if (sanitized !== originalContent) {
            fs.writeFileSync(filePath, sanitized, 'utf-8');
            sanitizedFiles.push(javaFile);
            removedReferences[javaFile] = missingTypes;
            console.log(`[Sanitize] ${javaFile}: saved successfully`);
        }
    }

    return { sanitizedFiles, removedReferences };
}

/**
 * Finds entity type names referenced in the Java source that are neither
 * present in the directory nor standard Java types.
 */
function findMissingReferencedTypes(content, presentTypes, standardTypes) {
    const missing = new Set();

    // Match field declarations with entity types: `private TypeName varName`
    // and collection types: `private Set<TypeName> varName`
    const fieldPatterns = [
        /private\s+Set<(\w+)>/g,
        /private\s+List<(\w+)>/g,
        /private\s+Collection<(\w+)>/g,
    ];

    for (const pattern of fieldPatterns) {
        let match;
        while ((match = pattern.exec(content)) !== null) {
            const typeName = match[1];
            if (!presentTypes.has(typeName) && !standardTypes.has(typeName)) {
                missing.add(typeName);
            }
        }
    }

    // Match direct entity type references in fields (ManyToOne):
    // `private Orders orders;`
    const directFieldPattern = /private\s+([A-Z]\w+)\s+\w+\s*[;=]/g;
    let match;
    while ((match = directFieldPattern.exec(content)) !== null) {
        const typeName = match[1];
        if (!presentTypes.has(typeName) && !standardTypes.has(typeName)) {
            missing.add(typeName);
        }
    }

    // Match types in method signatures (getters/setters)
    const methodTypePattern = /public\s+(?:Set<|List<|Collection<)?(\w+)>?\s+(?:get|set)\w+\s*\(/g;
    while ((match = methodTypePattern.exec(content)) !== null) {
        const typeName = match[1];
        if (!presentTypes.has(typeName) && !standardTypes.has(typeName) &&
            typeName !== 'void') {
            missing.add(typeName);
        }
    }

    return Array.from(missing);
}

/**
 * Removes all references to a specific type from the Java source.
 */
function removeTypeReferences(content, typeName) {
    let lines = content.split('\n');

    // Keep a copy of the original lines so we can look up field declarations
    // even after they've been removed from the working set
    const originalLines = [...lines];

    // 1. Remove field declarations referencing the type
    //    e.g. `     private Set<Orders> orderses = new HashSet<Orders>(0);`
    //    e.g. `     private Orders orders;`
    lines = lines.filter(line => {
        const trimmed = line.trim();
        if (trimmed.match(new RegExp(`private\\s+(?:Set|List|Collection)<${typeName}>\\s+\\w+`))) {
            return false;
        }
        if (trimmed.match(new RegExp(`private\\s+${typeName}\\s+\\w+\\s*[;=]`))) {
            return false;
        }
        return true;
    });

    // 2. Remove relationship annotations + getter/setter blocks
    //    Pattern: @OneToMany/@ManyToOne/@ManyToMany/@OneToOne annotation(s),
    //    possibly followed by @JoinColumn, then getter method referencing type,
    //    then blank lines, then setter method.
    lines = removeRelationshipBlock(lines, typeName);

    // 3. Clean constructor parameters and body assignments
    //    Pass originalLines so field lookups work even after step 1 removed them
    lines = cleanConstructorReferences(lines, typeName, originalLines);

    return lines.join('\n');
}

/**
 * Removes relationship annotation blocks (annotation + getter + setter)
 * for a given type.
 */
function removeRelationshipBlock(lines, typeName) {
    const result = [];
    let i = 0;

    while (i < lines.length) {
        const trimmed = lines[i].trim();

        // Detect a relationship annotation line
        if (isRelationshipAnnotation(trimmed)) {
            // Look ahead to see if the getter references our missing type
            const blockEnd = findRelationshipBlockEnd(lines, i, typeName);
            if (blockEnd > i) {
                // Skip the entire block (annotations + getter + setter)
                // Also skip any blank lines immediately before the annotation
                while (result.length > 0 && result[result.length - 1].trim() === '') {
                    result.pop();
                }
                i = blockEnd;
                continue;
            }
        }

        // Also detect getter/setter that references the type directly
        // (in case the annotation was on the same line or already removed)
        if (trimmed.match(new RegExp(`public\\s+(?:Set<|List<|Collection<)?${typeName}>?\\s+get\\w+\\s*\\(`)) ||
            trimmed.match(new RegExp(`public\\s+void\\s+set\\w+\\s*\\((?:Set<|List<|Collection<)?${typeName}`))) {
            // Remove this method block (until closing brace)
            const methodEnd = findMethodEnd(lines, i);
            // Remove preceding blank lines
            while (result.length > 0 && result[result.length - 1].trim() === '') {
                result.pop();
            }
            i = methodEnd;
            continue;
        }

        result.push(lines[i]);
        i++;
    }

    return result;
}

/**
 * Checks if a line is a JPA relationship annotation.
 */
function isRelationshipAnnotation(trimmedLine) {
    return /^@(OneToMany|ManyToOne|ManyToMany|OneToOne)\s*\(/.test(trimmedLine);
}

/**
 * Starting from a relationship annotation at line index `start`, finds the end
 * of the full block (annotation(s) + getter + setter) if the getter references
 * the given type. Returns the index of the line AFTER the block, or -1 if
 * this block does not reference the type.
 */
function findRelationshipBlockEnd(lines, start, typeName) {
    let i = start;

    // Consume annotation lines (@OneToMany, @JoinColumn, @JoinTable, etc.)
    while (i < lines.length) {
        const trimmed = lines[i].trim();
        if (trimmed.startsWith('@') || trimmed === '') {
            i++;
            continue;
        }
        break;
    }

    // Now we should be at the getter method line
    if (i >= lines.length) return -1;

    const getterLine = lines[i].trim();
    // Check if the getter returns our missing type
    const refersToType = getterLine.match(
        new RegExp(`(?:Set<|List<|Collection<)?${typeName}>?\\s+get\\w+\\s*\\(`)
    );
    if (!refersToType) return -1;

    // Find end of getter method
    i = findMethodEnd(lines, i);

    // Skip blank lines between getter and setter
    while (i < lines.length && lines[i].trim() === '') {
        i++;
    }

    // Check for setter method
    if (i < lines.length) {
        const setterLine = lines[i].trim();
        if (setterLine.match(new RegExp(`public\\s+void\\s+set\\w+\\s*\\((?:Set<|List<|Collection<)?${typeName}`))) {
            i = findMethodEnd(lines, i);
        }
    }

    return i;
}

/**
 * Finds the end of a method block starting at line `start`.
 * Returns the index of the line AFTER the closing brace.
 */
function findMethodEnd(lines, start) {
    let braceCount = 0;
    let foundBrace = false;
    let i = start;

    while (i < lines.length) {
        const line = lines[i];
        for (const ch of line) {
            if (ch === '{') {
                braceCount++;
                foundBrace = true;
            } else if (ch === '}') {
                braceCount--;
            }
        }
        i++;
        if (foundBrace && braceCount === 0) {
            break;
        }
    }

    return i;
}

/**
 * Removes constructor parameters and body assignments referencing the type.
 * @param {string[]} lines - Current working lines
 * @param {string} typeName - The missing type to remove
 * @param {string[]} originalLines - Original unmodified lines for field lookups
 */
function cleanConstructorReferences(lines, typeName, originalLines) {
    const result = [];

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Match constructor declarations that contain the type as a parameter
        // Two patterns to handle:
        // 1. Collection parameter: `Set<Orders> orderses`
        // 2. Direct entity parameter: `Orders orders`
        if (line.match(/public\s+\w+\s*\(/) && (
            line.includes(`${typeName} `) || line.includes(`${typeName}>`)
        )) {
            line = removeConstructorParameter(line, typeName);
        }

        // Remove `this.fieldName = fieldName;` lines where fieldName matches
        // a relationship field. We use originalLines for the lookup so we can
        // find the field declaration even though it was already removed in step 1.
        const trimmed = line.trim();
        const assignMatch = trimmed.match(/this\.(\w+)\s*=\s*(\w+)\s*;/);
        if (assignMatch && assignMatch[1] === assignMatch[2] &&
            isFieldOfMissingType(originalLines, assignMatch[1], typeName)) {
            continue; // skip this line
        }

        result.push(line);
    }

    return result;
}

/**
 * Removes a constructor parameter of the given type from a constructor declaration.
 */
function removeConstructorParameter(line, typeName) {
    // Remove `, Set<TypeName> varName` or `Set<TypeName> varName, ` or just `Set<TypeName> varName`
    // Also handles `TypeName varName` for ManyToOne references
    const patterns = [
        // Collection with trailing comma: `, Set<Type> name)`  =>  `)`
        new RegExp(`,\\s*(?:Set|List|Collection)<${typeName}>\\s+\\w+`),
        // Collection with leading comma: `(... , Set<Type> name`
        new RegExp(`(?:Set|List|Collection)<${typeName}>\\s+\\w+\\s*,\\s*`),
        // Direct type with trailing comma
        new RegExp(`,\\s*${typeName}\\s+\\w+`),
        // Direct type with leading comma
        new RegExp(`${typeName}\\s+\\w+\\s*,\\s*`),
    ];

    for (const pattern of patterns) {
        if (pattern.test(line)) {
            line = line.replace(pattern, '');
            break;
        }
    }

    return line;
}

/**
 * Heuristic to determine if a `this.x = x;` assignment corresponds to a
 * field of the missing type. Searches the original (unmodified) lines for
 * the field declaration to confirm the field's type.
 *
 * @param {string[]} originalLines - The original file lines (before any removals)
 * @param {number} _lineIndex - Not used (indices shift after filtering); we match by content
 * @param {string} typeName - The missing entity type name
 */
function isFieldForMissingType(originalLines, _lineIndex, typeName) {
    // This function is called with the current line already extracted by the caller.
    // We just need to check if the field name exists as a field of the missing type
    // in the original source. The caller checks `lines[i]` which is the current
    // working line — we receive originalLines to search for the declaration.

    // We can't rely on _lineIndex because lines may have shifted.
    // Instead, the caller already verified the line matches `this.X = X;`
    // so we return true if ANY field of this type exists in the original.
    // Since this function is called once per `this.x = x;` line, we need the
    // actual field name. The caller should pass it, but for backwards compat
    // we accept the current approach.

    // Actually, let's just return false here — the caller will re-check.
    // We need to refactor this to receive the field name directly.
    return false;
}

/**
 * Checks if a given field name corresponds to a field of the missing type
 * by searching the original (unmodified) lines for its declaration.
 *
 * @param {string[]} originalLines - The original file lines (before any removals)
 * @param {string} fieldName - The field name from `this.fieldName = fieldName;`
 * @param {string} typeName - The missing entity type name
 * @returns {boolean}
 */
function isFieldOfMissingType(originalLines, fieldName, typeName) {
    for (let j = 0; j < originalLines.length; j++) {
        const t = originalLines[j].trim();
        if (t.match(new RegExp(`private\\s+(?:Set|List|Collection)<${typeName}>\\s+${fieldName}`)) ||
            t.match(new RegExp(`private\\s+${typeName}\\s+${fieldName}`))) {
            return true;
        }
    }
    return false;
}

/**
 * Removes import statements that are no longer referenced in the file body.
 */
function cleanupUnusedImports(content) {
    const lines = content.split('\n');
    const importLines = [];
    const bodyLines = [];

    // Separate imports from the rest
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim().startsWith('import ')) {
            importLines.push({ index: i, line: lines[i] });
        }
    }

    // Build the body (everything except import lines)
    const bodyContent = lines.filter(l => !l.trim().startsWith('import ')).join('\n');

    const result = [...lines];
    const toRemove = new Set();

    for (const imp of importLines) {
        const trimmed = imp.line.trim();
        // Extract the simple class name from the import
        const importMatch = trimmed.match(/import\s+[\w.]+\.(\w+)\s*;/);
        if (!importMatch) continue;

        const className = importMatch[1];

        // Check if this class name is still used in the body
        // Use word boundary to avoid false matches
        const usagePattern = new RegExp(`\\b${className}\\b`);
        if (!usagePattern.test(bodyContent)) {
            toRemove.add(imp.index);
        }
    }

    if (toRemove.size === 0) return content;

    return lines.filter((_, i) => !toRemove.has(i)).join('\n');
}

module.exports = {
    sanitizeEntityRelationships,
    findMissingReferencedTypes,
    removeTypeReferences,
    cleanupUnusedImports,
};
