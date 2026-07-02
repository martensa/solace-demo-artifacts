//
// Source code recreated from a .class file by IntelliJ IDEA
// (powered by FernFlower decompiler)
//

package com.solace.connectors.database.sink.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

@Entity
@Table(
        name = "TB_ACCESS_LOG"
)
public class TbAccessLog implements Serializable {
    private BigDecimal id;
    private String txDirection;
    private String requestUri;
    private String txId;
    private String clientSystemId;
    private Date clientTimestamp;
    private String clientMsgId;
    private String txGuid;
    private String parentTxGuidSeq;
    private String txGuidSeq;
    private String globalId;
    private String ecFlag;
    private String ecTxGuid;
    private String ecTxGuidSeq;
    private String txResult;
    private String txStatusCode;
    private String clientIp;
    private BigDecimal clientPort;
    private String createdBy;
    private Date createdTimestamp;
    private String updatedBy;
    private Date updatedTimestamp;

    public TbAccessLog() {
    }

    public TbAccessLog(BigDecimal id, String txDirection, String requestUri, String txId, String clientSystemId, Date clientTimestamp, String clientMsgId, String txGuid, String txGuidSeq) {
        this.id = id;
        this.txDirection = txDirection;
        this.requestUri = requestUri;
        this.txId = txId;
        this.clientSystemId = clientSystemId;
        this.clientTimestamp = clientTimestamp;
        this.clientMsgId = clientMsgId;
        this.txGuid = txGuid;
        this.txGuidSeq = txGuidSeq;
    }

    public TbAccessLog(BigDecimal id, String txDirection, String requestUri, String txId, String clientSystemId, Date clientTimestamp, String clientMsgId, String txGuid, String parentTxGuidSeq, String txGuidSeq, String globalId, String ecFlag, String ecTxGuid, String ecTxGuidSeq, String txResult, String txStatusCode, String clientIp, BigDecimal clientPort, String createdBy, Date createdTimestamp, String updatedBy, Date updatedTimestamp) {
        this.id = id;
        this.txDirection = txDirection;
        this.requestUri = requestUri;
        this.txId = txId;
        this.clientSystemId = clientSystemId;
        this.clientTimestamp = clientTimestamp;
        this.clientMsgId = clientMsgId;
        this.txGuid = txGuid;
        this.parentTxGuidSeq = parentTxGuidSeq;
        this.txGuidSeq = txGuidSeq;
        this.globalId = globalId;
        this.ecFlag = ecFlag;
        this.ecTxGuid = ecTxGuid;
        this.ecTxGuidSeq = ecTxGuidSeq;
        this.txResult = txResult;
        this.txStatusCode = txStatusCode;
        this.clientIp = clientIp;
        this.clientPort = clientPort;
        this.createdBy = createdBy;
        this.createdTimestamp = createdTimestamp;
        this.updatedBy = updatedBy;
        this.updatedTimestamp = updatedTimestamp;
    }

    @Id
    @Column(
            name = "ID",
            unique = true,
            nullable = false,
            scale = 0
    )
    public BigDecimal getId() {
        return this.id;
    }

    public void setId(BigDecimal id) {
        this.id = id;
    }

    @Column(
            name = "TX_DIRECTION",
            nullable = false,
            length = 2
    )
    public String getTxDirection() {
        return this.txDirection;
    }

    public void setTxDirection(String txDirection) {
        this.txDirection = txDirection;
    }

    @Column(
            name = "REQUEST_URI",
            nullable = false,
            length = 128
    )
    public String getRequestUri() {
        return this.requestUri;
    }

    public void setRequestUri(String requestUri) {
        this.requestUri = requestUri;
    }

    @Column(
            name = "TX_ID",
            nullable = false,
            length = 20
    )
    public String getTxId() {
        return this.txId;
    }

    public void setTxId(String txId) {
        this.txId = txId;
    }

    @Column(
            name = "CLIENT_SYSTEM_ID",
            nullable = false,
            length = 10
    )
    public String getClientSystemId() {
        return this.clientSystemId;
    }

    public void setClientSystemId(String clientSystemId) {
        this.clientSystemId = clientSystemId;
    }

    @Column(
            name = "CLIENT_TIMESTAMP",
            nullable = false,
            length = 11
    )
    public Date getClientTimestamp() {
        return this.clientTimestamp;
    }

    public void setClientTimestamp(Date clientTimestamp) {
        this.clientTimestamp = clientTimestamp;
    }

    @Column(
            name = "CLIENT_MSG_ID",
            nullable = false,
            length = 50
    )
    public String getClientMsgId() {
        return this.clientMsgId;
    }

    public void setClientMsgId(String clientMsgId) {
        this.clientMsgId = clientMsgId;
    }

    @Column(
            name = "TX_GUID",
            nullable = false,
            length = 50
    )
    public String getTxGuid() {
        return this.txGuid;
    }

    public void setTxGuid(String txGuid) {
        this.txGuid = txGuid;
    }

    @Column(
            name = "PARENT_TX_GUID_SEQ",
            length = 3
    )
    public String getParentTxGuidSeq() {
        return this.parentTxGuidSeq;
    }

    public void setParentTxGuidSeq(String parentTxGuidSeq) {
        this.parentTxGuidSeq = parentTxGuidSeq;
    }

    @Column(
            name = "TX_GUID_SEQ",
            nullable = false,
            length = 3
    )
    public String getTxGuidSeq() {
        return this.txGuidSeq;
    }

    public void setTxGuidSeq(String txGuidSeq) {
        this.txGuidSeq = txGuidSeq;
    }

    @Column(
            name = "GLOBAL_ID",
            length = 50
    )
    public String getGlobalId() {
        return this.globalId;
    }

    public void setGlobalId(String globalId) {
        this.globalId = globalId;
    }

    @Column(
            name = "EC_FLAG",
            length = 2
    )
    public String getEcFlag() {
        return this.ecFlag;
    }

    public void setEcFlag(String ecFlag) {
        this.ecFlag = ecFlag;
    }

    @Column(
            name = "EC_TX_GUID",
            length = 50
    )
    public String getEcTxGuid() {
        return this.ecTxGuid;
    }

    public void setEcTxGuid(String ecTxGuid) {
        this.ecTxGuid = ecTxGuid;
    }

    @Column(
            name = "EC_TX_GUID_SEQ",
            length = 3
    )
    public String getEcTxGuidSeq() {
        return this.ecTxGuidSeq;
    }

    public void setEcTxGuidSeq(String ecTxGuidSeq) {
        this.ecTxGuidSeq = ecTxGuidSeq;
    }

    @Column(
            name = "TX_RESULT",
            length = 1
    )
    public String getTxResult() {
        return this.txResult;
    }

    public void setTxResult(String txResult) {
        this.txResult = txResult;
    }

    @Column(
            name = "TX_STATUS_CODE",
            length = 10
    )
    public String getTxStatusCode() {
        return this.txStatusCode;
    }

    public void setTxStatusCode(String txStatusCode) {
        this.txStatusCode = txStatusCode;
    }

    @Column(
            name = "CLIENT_IP",
            length = 50
    )
    public String getClientIp() {
        return this.clientIp;
    }

    public void setClientIp(String clientIp) {
        this.clientIp = clientIp;
    }

    @Column(
            name = "CLIENT_PORT",
            precision = 5,
            scale = 0
    )
    public BigDecimal getClientPort() {
        return this.clientPort;
    }

    public void setClientPort(BigDecimal clientPort) {
        this.clientPort = clientPort;
    }

    @Column(
            name = "CREATED_BY",
            length = 20
    )
    public String getCreatedBy() {
        return this.createdBy;
    }

    public void setCreatedBy(String createdBy) {
        this.createdBy = createdBy;
    }

    @Column(
            name = "CREATED_TIMESTAMP",
            length = 11
    )
    public Date getCreatedTimestamp() {
        return this.createdTimestamp;
    }

    public void setCreatedTimestamp(Date createdTimestamp) {
        this.createdTimestamp = createdTimestamp;
    }

    @Column(
            name = "UPDATED_BY",
            length = 20
    )
    public String getUpdatedBy() {
        return this.updatedBy;
    }

    public void setUpdatedBy(String updatedBy) {
        this.updatedBy = updatedBy;
    }

    @Column(
            name = "UPDATED_TIMESTAMP",
            length = 11
    )
    public Date getUpdatedTimestamp() {
        return this.updatedTimestamp;
    }

    public void setUpdatedTimestamp(Date updatedTimestamp) {
        this.updatedTimestamp = updatedTimestamp;
    }
}
