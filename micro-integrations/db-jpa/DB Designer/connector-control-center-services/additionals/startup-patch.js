/**
 * Startup patch loader.
 *
 * This file is placed in the additionals directory which is mounted
 * into the Docker container. It loads the DB CLI entity generation
 * patch at service startup.
 *
 * To activate, the Dockerfile CMD or www.js needs to require this file,
 * or it can be loaded via Node.js --require flag.
 */

const path = require('path');

try {
    const patchPath = path.resolve(__dirname, '..', 'artifacts', 'tools', 'patch-entity-generation.js');
    console.log(`[Startup] Loading DB CLI entity generation patch from: ${patchPath}`);
    const { applyPatch } = require(patchPath);
    applyPatch();
} catch (error) {
    console.error(`[Startup] Could not load DB CLI patch: ${error.message}`);
    console.error(`[Startup] Service will continue with original Hibernate Tools entity generation.`);
}
