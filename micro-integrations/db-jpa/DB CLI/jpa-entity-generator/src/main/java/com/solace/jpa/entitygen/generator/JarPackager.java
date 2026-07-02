package com.solace.jpa.entitygen.generator;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.jar.*;

/**
 * Packages generated source files into a JAR file.
 * The JAR contains compiled sources organized by package structure.
 */
public class JarPackager {

    private static final Logger log = LoggerFactory.getLogger(JarPackager.class);

    /**
     * Compiles Java sources and packages them into a JAR.
     *
     * @param sourceDir  root directory containing the package structure with .java files
     * @param outputJar  path to the output JAR file
     * @param basePackage the base package name (e.g., "com.example.entity")
     */
    public void packageJar(Path sourceDir, Path outputJar, String basePackage) throws IOException {
        Files.createDirectories(outputJar.getParent());

        // First, try to compile the sources
        Path classesDir = sourceDir.getParent().resolve("classes");
        boolean compiled = compile(sourceDir, classesDir);

        // Package either compiled classes or source files
        Path contentDir = compiled ? classesDir : sourceDir;

        Manifest manifest = new Manifest();
        manifest.getMainAttributes().put(Attributes.Name.MANIFEST_VERSION, "1.0");
        manifest.getMainAttributes().putValue("Created-By", "JPA Entity Generator CLI");
        manifest.getMainAttributes().putValue("Base-Package", basePackage);

        try (JarOutputStream jos = new JarOutputStream(
                new BufferedOutputStream(Files.newOutputStream(outputJar)), manifest)) {

            Files.walkFileTree(contentDir, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                    String extension = compiled ? ".class" : ".java";
                    if (file.toString().endsWith(extension)) {
                        String entryName = contentDir.relativize(file).toString()
                                .replace(File.separatorChar, '/');
                        jos.putNextEntry(new JarEntry(entryName));
                        Files.copy(file, jos);
                        jos.closeEntry();
                    }
                    return FileVisitResult.CONTINUE;
                }
            });
        }

        long sizeKb = Files.size(outputJar) / 1024;
        log.info("Packaged JAR: {} ({} KB)", outputJar.getFileName(), sizeKb);
    }

    /**
     * Attempts to compile Java sources using javac.
     * Returns true if compilation succeeded, false otherwise.
     */
    private boolean compile(Path sourceDir, Path classesDir) {
        try {
            Files.createDirectories(classesDir);

            // Collect all .java files
            var javaFiles = new java.util.ArrayList<String>();
            Files.walkFileTree(sourceDir, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                    if (file.toString().endsWith(".java")) {
                        javaFiles.add(file.toAbsolutePath().toString());
                    }
                    return FileVisitResult.CONTINUE;
                }
            });

            if (javaFiles.isEmpty()) {
                log.warn("No .java files found to compile");
                return false;
            }

            // Build javac command
            var command = new java.util.ArrayList<String>();
            command.add("javac");
            command.add("-d");
            command.add(classesDir.toAbsolutePath().toString());
            String javaVersion = detectTargetVersion();
            command.add("-source");
            command.add(javaVersion);
            command.add("-target");
            command.add(javaVersion);
            command.add("-cp");
            command.add(getCompileClasspath());
            command.addAll(javaFiles);

            ProcessBuilder pb = new ProcessBuilder(command);
            pb.inheritIO();
            Process process = pb.start();
            int exitCode = process.waitFor();

            if (exitCode == 0) {
                log.info("Successfully compiled {} source file(s)", javaFiles.size());
                return true;
            } else {
                log.warn("Compilation failed (exit code {}). JAR will contain source files instead.", exitCode);
                return false;
            }
        } catch (Exception e) {
            log.warn("Compilation skipped ({}). JAR will contain source files.", e.getMessage());
            return false;
        }
    }

    /**
     * Detects the Java version to use for compilation.
     * Defaults to the runtime version, clamped to a minimum of 17.
     */
    private String detectTargetVersion() {
        String override = System.getenv("DB_CLI_JAVA_TARGET");
        if (override != null && !override.isBlank()) {
            return override.trim();
        }
        int runtimeVersion = Runtime.version().feature();
        int target = Math.max(runtimeVersion, 17);
        return String.valueOf(target);
    }

    /**
     * Builds a classpath string with JPA and Spring Data dependencies.
     * Dynamically discovers JAR files from the Maven local repository,
     * so it works regardless of the specific dependency versions installed.
     */
    private String getCompileClasspath() {
        String mavenRepo = System.getProperty("user.home") + "/.m2/repository";
        StringBuilder cp = new StringBuilder();

        // Artifact directories to search (version-agnostic)
        String[] artifactDirs = {
                "jakarta/persistence/jakarta.persistence-api",
                "org/springframework/data/spring-data-jpa",
                "org/springframework/data/spring-data-commons",
                "org/springframework/spring-context",
                "org/springframework/spring-tx",
                "org/springframework/spring-beans",
                "org/springframework/spring-core",
                "com/fasterxml/jackson/core/jackson-annotations",
                "org/hibernate/orm/hibernate-core",
                "jakarta/annotation/jakarta.annotation-api"
        };

        for (String artifactDir : artifactDirs) {
            Path dir = Path.of(mavenRepo, artifactDir);
            Path jar = findLatestJar(dir);
            if (jar != null) {
                if (!cp.isEmpty()) cp.append(File.pathSeparator);
                cp.append(jar);
            }
        }

        return cp.toString();
    }

    /**
     * Finds the latest versioned JAR in a Maven artifact directory.
     * Scans version subdirectories and picks the most recently modified JAR.
     */
    private Path findLatestJar(Path artifactDir) {
        if (!Files.isDirectory(artifactDir)) return null;
        try (var versions = Files.list(artifactDir)) {
            return versions
                    .filter(Files::isDirectory)
                    .sorted((a, b) -> {
                        // Sort by last modified time descending to prefer latest version
                        try {
                            return Long.compare(
                                    Files.getLastModifiedTime(b).toMillis(),
                                    Files.getLastModifiedTime(a).toMillis());
                        } catch (IOException e) {
                            return 0;
                        }
                    })
                    .flatMap(versionDir -> {
                        try {
                            return Files.list(versionDir)
                                    .filter(f -> f.toString().endsWith(".jar")
                                            && !f.toString().endsWith("-sources.jar")
                                            && !f.toString().endsWith("-javadoc.jar"));
                        } catch (IOException e) {
                            return java.util.stream.Stream.empty();
                        }
                    })
                    .findFirst()
                    .orElse(null);
        } catch (IOException e) {
            return null;
        }
    }
}
