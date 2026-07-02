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
        name = "CUSTOMER"
)
public class Customer implements Serializable {
    private BigDecimal customerId;
    private String adbTrackingid;
    private String DStatus;
    private String sequenceId;
    private String city;
    private String firstName;
    private String lastName;
    private String state;
    private String zip;
    private Date dbtime;
    private byte[] blobc;
    private String clobc;
    private Date systemtime;

    public Customer() {
    }

    public Customer(BigDecimal customerId) {
        this.customerId = customerId;
    }

    public Customer(BigDecimal customerId, String adbTrackingid, String DStatus, String sequenceId, String city, String firstName, String lastName, String state, String zip, Date dbtime, byte[] blobc, String clobc, Date systemtime) {
        this.customerId = customerId;
        this.adbTrackingid = adbTrackingid;
        this.DStatus = DStatus;
        this.sequenceId = sequenceId;
        this.city = city;
        this.firstName = firstName;
        this.lastName = lastName;
        this.state = state;
        this.zip = zip;
        this.dbtime = dbtime;
        this.blobc = blobc;
        this.clobc = clobc;
        this.systemtime = systemtime;
    }

    @Id
    @Column(
            name = "CUSTOMER_ID",
            unique = true,
            nullable = false,
            precision = 38
    )
    public BigDecimal getCustomerId() {
        return this.customerId;
    }

    public void setCustomerId(BigDecimal customerId) {
        this.customerId = customerId;
    }

    @Column(
            name = "ADB_TRACKINGID"
    )
    public String getAdbTrackingid() {
        return this.adbTrackingid;
    }

    public void setAdbTrackingid(String adbTrackingid) {
        this.adbTrackingid = adbTrackingid;
    }

    @Column(
            name = "D_STATUS",
            length = 5
    )
    public String getDStatus() {
        return this.DStatus;
    }

    public void setDStatus(String DStatus) {
        this.DStatus = DStatus;
    }

    @Column(
            name = "SEQUENCE_ID",
            length = 50
    )
    public String getSequenceId() {
        return this.sequenceId;
    }

    public void setSequenceId(String sequenceId) {
        this.sequenceId = sequenceId;
    }

    @Column(
            name = "CITY"
    )
    public String getCity() {
        return this.city;
    }

    public void setCity(String city) {
        this.city = city;
    }

    @Column(
            name = "FIRST_NAME"
    )
    public String getFirstName() {
        return this.firstName;
    }

    public void setFirstName(String firstName) {
        this.firstName = firstName;
    }

    @Column(
            name = "LAST_NAME"
    )
    public String getLastName() {
        return this.lastName;
    }

    public void setLastName(String lastName) {
        this.lastName = lastName;
    }

    @Column(
            name = "STATE"
    )
    public String getState() {
        return this.state;
    }

    public void setState(String state) {
        this.state = state;
    }

    @Column(
            name = "ZIP"
    )
    public String getZip() {
        return this.zip;
    }

    public void setZip(String zip) {
        this.zip = zip;
    }

    @Column(
            name = "DBTIME",
            length = 11
    )
    public Date getDbtime() {
        return this.dbtime;
    }

    public void setDbtime(Date dbtime) {
        this.dbtime = dbtime;
    }

    @Column(
            name = "BLOBC"
    )
    public byte[] getBlobc() {
        return this.blobc;
    }

    public void setBlobc(byte[] blobc) {
        this.blobc = blobc;
    }

    @Column(
            name = "CLOBC"
    )
    public String getClobc() {
        return this.clobc;
    }

    public void setClobc(String clobc) {
        this.clobc = clobc;
    }

    @Column(
            name = "SYSTEMTIME",
            length = 11
    )
    public Date getSystemtime() {
        return this.systemtime;
    }

    public void setSystemtime(Date systemtime) {
        this.systemtime = systemtime;
    }
}
