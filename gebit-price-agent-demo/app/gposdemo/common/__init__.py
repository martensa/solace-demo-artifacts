"""Shared library of all gpos-demo services (WP-A, UC1-BUILD-SPEC 2.4).

Modules: config, clock, fmt, money, jsonutil, ids, db, bus, topics, outbox,
descriptors, grpcutil, mcputil, telemetry, protoc, log. Import the module you need
(``from gposdemo.common import bus``); nothing is re-exported here so that importing
one module never pulls in heavy optional dependencies of another.
"""
