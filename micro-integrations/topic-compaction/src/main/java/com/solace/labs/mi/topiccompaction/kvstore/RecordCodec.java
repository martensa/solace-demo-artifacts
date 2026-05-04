package com.solace.labs.mi.topiccompaction.kvstore;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Length-prefixed binary codec for {@link CompactedRecord}.
 *
 * <p>Format (little explanation, deliberately stable & simple - we never need to
 * read this with another tool):
 * <pre>
 *   version    : 1 byte (currently 1)
 *   topicLen   : varint
 *   topic      : UTF-8 bytes
 *   ingestTs   : long (8 bytes)
 *   senderTs   : long (8 bytes); -1 if absent
 *   headerCnt  : varint
 *   for each header:
 *     keyLen   : varint
 *     key      : UTF-8 bytes
 *     valType  : 1 byte (0=string, 1=long, 2=int, 3=byte[], 4=bool, 99=unsupported-toString)
 *     valLen   : varint  (only for string/byte[])
 *     val      : bytes per type
 *   payloadLen : varint
 *   payload    : bytes
 * </pre>
 *
 * <p>We avoid Java serialization (insecure) and Jackson (overhead, harder to
 * version). For headers we serialize common types and fall back to {@code toString()}
 * for everything else, which is good enough for compacted-replay semantics where
 * the payload is the source of truth.
 */
final class RecordCodec {

    private static final byte VERSION = 1;
    private static final byte TYPE_STRING = 0;
    private static final byte TYPE_LONG = 1;
    private static final byte TYPE_INT = 2;
    private static final byte TYPE_BYTES = 3;
    private static final byte TYPE_BOOL = 4;
    private static final byte TYPE_TOSTRING = 99;

    private RecordCodec() {}

    static byte[] encode(CompactedRecord record) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream(record.payload().length + 256);
             DataOutputStream out = new DataOutputStream(baos)) {
            out.writeByte(VERSION);
            writeString(out, record.originalTopic());
            out.writeLong(record.ingestTimestamp());
            out.writeLong(record.senderTimestamp() == null ? -1L : record.senderTimestamp());
            writeVarInt(out, record.headers().size());
            for (Map.Entry<String, Object> e : record.headers().entrySet()) {
                writeString(out, e.getKey());
                writeHeaderValue(out, e.getValue());
            }
            writeVarInt(out, record.payload().length);
            out.write(record.payload());
            return baos.toByteArray();
        } catch (IOException e) {
            throw new UncheckedIOException("Failed to encode CompactedRecord", e);
        }
    }

    static CompactedRecord decode(byte[] bytes) {
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes))) {
            byte version = in.readByte();
            if (version != VERSION) {
                throw new IllegalStateException("Unsupported record version: " + version);
            }
            String topic = readString(in);
            long ingestTs = in.readLong();
            long senderTs = in.readLong();
            int headerCount = readVarInt(in);
            Map<String, Object> headers = new LinkedHashMap<>(headerCount);
            for (int i = 0; i < headerCount; i++) {
                String key = readString(in);
                Object value = readHeaderValue(in);
                headers.put(key, value);
            }
            int payloadLen = readVarInt(in);
            byte[] payload = in.readNBytes(payloadLen);
            return new CompactedRecord(payload, headers, topic, ingestTs, senderTs == -1L ? null : senderTs);
        } catch (IOException e) {
            throw new UncheckedIOException("Failed to decode CompactedRecord", e);
        }
    }

    private static void writeHeaderValue(DataOutputStream out, Object value) throws IOException {
        if (value instanceof String s) {
            out.writeByte(TYPE_STRING);
            byte[] b = s.getBytes(StandardCharsets.UTF_8);
            writeVarInt(out, b.length);
            out.write(b);
        } else if (value instanceof Long l) {
            out.writeByte(TYPE_LONG);
            out.writeLong(l);
        } else if (value instanceof Integer i) {
            out.writeByte(TYPE_INT);
            out.writeInt(i);
        } else if (value instanceof byte[] b) {
            out.writeByte(TYPE_BYTES);
            writeVarInt(out, b.length);
            out.write(b);
        } else if (value instanceof Boolean bool) {
            out.writeByte(TYPE_BOOL);
            out.writeByte(bool ? 1 : 0);
        } else {
            out.writeByte(TYPE_TOSTRING);
            byte[] b = String.valueOf(value).getBytes(StandardCharsets.UTF_8);
            writeVarInt(out, b.length);
            out.write(b);
        }
    }

    private static Object readHeaderValue(DataInputStream in) throws IOException {
        byte type = in.readByte();
        return switch (type) {
            case TYPE_STRING, TYPE_TOSTRING -> {
                int len = readVarInt(in);
                yield new String(in.readNBytes(len), StandardCharsets.UTF_8);
            }
            case TYPE_LONG -> in.readLong();
            case TYPE_INT -> in.readInt();
            case TYPE_BYTES -> {
                int len = readVarInt(in);
                yield in.readNBytes(len);
            }
            case TYPE_BOOL -> in.readByte() != 0;
            default -> throw new IllegalStateException("Unknown header value type: " + type);
        };
    }

    private static void writeString(DataOutputStream out, String s) throws IOException {
        byte[] bytes = s.getBytes(StandardCharsets.UTF_8);
        writeVarInt(out, bytes.length);
        out.write(bytes);
    }

    private static String readString(DataInputStream in) throws IOException {
        int len = readVarInt(in);
        return new String(in.readNBytes(len), StandardCharsets.UTF_8);
    }

    private static void writeVarInt(DataOutputStream out, int value) throws IOException {
        while ((value & ~0x7F) != 0) {
            out.writeByte((value & 0x7F) | 0x80);
            value >>>= 7;
        }
        out.writeByte(value);
    }

    private static int readVarInt(DataInputStream in) throws IOException {
        int result = 0;
        int shift = 0;
        while (true) {
            byte b = in.readByte();
            result |= (b & 0x7F) << shift;
            if ((b & 0x80) == 0) return result;
            shift += 7;
            if (shift > 35) throw new IOException("VarInt too long");
        }
    }
}
