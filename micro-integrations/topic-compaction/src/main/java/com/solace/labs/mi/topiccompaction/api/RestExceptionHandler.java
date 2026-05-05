package com.solace.labs.mi.topiccompaction.api;

import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/**
 * Global REST exception translator. Converts known exception types to
 * {@code application/problem+json} responses (RFC-7807 Problem
 * Details) so clients get a consistent error envelope.
 *
 * <p>Scope is restricted to the API package so that errors raised in
 * Spring Cloud Stream interceptors keep the framework's default
 * handling.
 */
@ControllerAdvice(basePackages = "com.solace.labs.mi.topiccompaction.api")
public class RestExceptionHandler {

    private static final Logger log =
            LoggerFactory.getLogger(RestExceptionHandler.class);

    /** {@code 400} Validation rejected the input. */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ProblemDetail> handleConstraintViolation(
            ConstraintViolationException e) {
        return problem(HttpStatus.BAD_REQUEST,
                "Invalid request parameter", e.getMessage());
    }

    /** {@code 400} Body validation rejected the input. */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ProblemDetail> handleMethodArgumentNotValid(
            MethodArgumentNotValidException e) {
        String detail = e.getBindingResult().getAllErrors().stream()
                .map(err -> err.getDefaultMessage() == null
                        ? "invalid" : err.getDefaultMessage())
                .reduce((a, b) -> a + "; " + b).orElse("invalid request body");
        return problem(HttpStatus.BAD_REQUEST,
                "Invalid request body", detail);
    }

    /** {@code 400} A required query parameter is missing. */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<ProblemDetail> handleMissingParam(
            MissingServletRequestParameterException e) {
        return problem(HttpStatus.BAD_REQUEST,
                "Missing required parameter",
                e.getParameterName() + " is required");
    }

    /** {@code 400} A query parameter could not be parsed. */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ProblemDetail> handleTypeMismatch(
            MethodArgumentTypeMismatchException e) {
        String required = e.getRequiredType() == null ? "valid value"
                : e.getRequiredType().getSimpleName();
        return problem(HttpStatus.BAD_REQUEST,
                "Invalid parameter type",
                e.getName() + " must be a " + required);
    }

    /** {@code 400} Catch-all for IllegalArgumentException. */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ProblemDetail> handleIllegalArgument(
            IllegalArgumentException e) {
        return problem(HttpStatus.BAD_REQUEST,
                "Invalid argument", e.getMessage());
    }

    /** {@code 405} HTTP method not supported on the resource. */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ProblemDetail> handleMethodNotSupported(
            HttpRequestMethodNotSupportedException e) {
        return problem(HttpStatus.METHOD_NOT_ALLOWED,
                "Method not allowed", e.getMessage());
    }

    /** {@code 500} Unhandled exception fallback. */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemDetail> handleGeneric(Exception e) {
        log.error("Unhandled exception in REST handler", e);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR,
                "Internal error",
                "An unexpected error occurred. See server logs.");
    }

    private static ResponseEntity<ProblemDetail> problem(
            HttpStatusCode status, String title, String detail) {
        ProblemDetail body = ProblemDetail.forStatus(status);
        body.setTitle(title);
        body.setDetail(detail);
        return ResponseEntity.status(status).body(body);
    }
}
