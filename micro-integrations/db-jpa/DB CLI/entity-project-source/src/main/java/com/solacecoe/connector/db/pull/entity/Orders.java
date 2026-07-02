
package com.solacecoe.connector.db.pull.entity;

import jakarta.persistence.*;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;

@Entity
@Table(
        name = "orders",
        schema = "public"
)
public class Orders implements Serializable {
    private BigDecimal orderId;
    private BigDecimal customerId;
    private BigDecimal paymentMethodId;
    private Date orderDate;
    private String status;
    private BigDecimal subtotal;
    private BigDecimal taxAmount;
    private BigDecimal shippingCost;
    private BigDecimal totalAmount;
    private String shippingAddressLine1;
    private String shippingAddressLine2;
    private String shippingCity;
    private String shippingState;
    private String shippingPostalCode;
    private String shippingCountry;
    private String notes;
    private Date createdAt;
    private Date updatedAt;

    public Orders() {
    }

    public Orders(BigDecimal orderId, BigDecimal customerId, BigDecimal subtotal, BigDecimal totalAmount) {
        this.orderId = orderId;
        this.customerId = customerId;
        this.subtotal = subtotal;
        this.totalAmount = totalAmount;
    }

    public Orders(BigDecimal orderId, BigDecimal customerId, BigDecimal paymentMethodId, Date orderDate, String status, BigDecimal subtotal, BigDecimal taxAmount, BigDecimal shippingCost, BigDecimal totalAmount, String shippingAddressLine1, String shippingAddressLine2, String shippingCity, String shippingState, String shippingPostalCode, String shippingCountry, String notes, Date createdAt, Date updatedAt) {
        this.orderId = orderId;
        this.customerId = customerId;
        this.paymentMethodId = paymentMethodId;
        this.orderDate = orderDate;
        this.status = status;
        this.subtotal = subtotal;
        this.taxAmount = taxAmount;
        this.shippingCost = shippingCost;
        this.totalAmount = totalAmount;
        this.shippingAddressLine1 = shippingAddressLine1;
        this.shippingAddressLine2 = shippingAddressLine2;
        this.shippingCity = shippingCity;
        this.shippingState = shippingState;
        this.shippingPostalCode = shippingPostalCode;
        this.shippingCountry = shippingCountry;
        this.notes = notes;
        this.createdAt = createdAt;
        this.updatedAt = updatedAt;
    }

    @Id
    @Column(
            name = "order_id",
            unique = true,
            nullable = false
    )
    public BigDecimal getOrderId() {
        return this.orderId;
    }

    public void setOrderId(BigDecimal orderId) {
        this.orderId = orderId;
    }


    @Column(
            name = "order_date",
            length = 29
    )
    public Date getOrderDate() {
        return this.orderDate;
    }

    public void setOrderDate(Date orderDate) {
        this.orderDate = orderDate;
    }

    @Column(
            name = "status",
            length = 50
    )
    public String getStatus() {
        return this.status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    @Column(
            name = "subtotal",
            nullable = false,
            precision = 10
    )
    public BigDecimal getSubtotal() {
        return this.subtotal;
    }

    public void setSubtotal(BigDecimal subtotal) {
        this.subtotal = subtotal;
    }

    @Column(
            name = "tax_amount",
            precision = 10
    )
    public BigDecimal getTaxAmount() {
        return this.taxAmount;
    }

    public void setTaxAmount(BigDecimal taxAmount) {
        this.taxAmount = taxAmount;
    }

    @Column(
            name = "shipping_cost",
            precision = 10
    )
    public BigDecimal getShippingCost() {
        return this.shippingCost;
    }

    public void setShippingCost(BigDecimal shippingCost) {
        this.shippingCost = shippingCost;
    }

    @Column(
            name = "total_amount",
            nullable = false,
            precision = 10
    )
    public BigDecimal getTotalAmount() {
        return this.totalAmount;
    }

    public void setTotalAmount(BigDecimal totalAmount) {
        this.totalAmount = totalAmount;
    }

    @Column(
            name = "shipping_address_line1"
    )
    public String getShippingAddressLine1() {
        return this.shippingAddressLine1;
    }

    public void setShippingAddressLine1(String shippingAddressLine1) {
        this.shippingAddressLine1 = shippingAddressLine1;
    }

    @Column(
            name = "shipping_address_line2"
    )
    public String getShippingAddressLine2() {
        return this.shippingAddressLine2;
    }

    public void setShippingAddressLine2(String shippingAddressLine2) {
        this.shippingAddressLine2 = shippingAddressLine2;
    }

    @Column(
            name = "shipping_city",
            length = 100
    )
    public String getShippingCity() {
        return this.shippingCity;
    }

    public void setShippingCity(String shippingCity) {
        this.shippingCity = shippingCity;
    }

    @Column(
            name = "shipping_state",
            length = 100
    )
    public String getShippingState() {
        return this.shippingState;
    }

    public void setShippingState(String shippingState) {
        this.shippingState = shippingState;
    }

    @Column(
            name = "shipping_postal_code",
            length = 20
    )
    public String getShippingPostalCode() {
        return this.shippingPostalCode;
    }

    public void setShippingPostalCode(String shippingPostalCode) {
        this.shippingPostalCode = shippingPostalCode;
    }

    @Column(
            name = "shipping_country",
            length = 100
    )
    public String getShippingCountry() {
        return this.shippingCountry;
    }

    public void setShippingCountry(String shippingCountry) {
        this.shippingCountry = shippingCountry;
    }

    @Column(
            name = "notes"
    )
    public String getNotes() {
        return this.notes;
    }

    public void setNotes(String notes) {
        this.notes = notes;
    }

    @Column(
            name = "created_at",
            length = 29
    )
    public Date getCreatedAt() {
        return this.createdAt;
    }

    public void setCreatedAt(Date createdAt) {
        this.createdAt = createdAt;
    }

    @Column(
            name = "updated_at",
            length = 29
    )
    public Date getUpdatedAt() {
        return this.updatedAt;
    }

    public void setUpdatedAt(Date updatedAt) {
        this.updatedAt = updatedAt;
    }

    //    @OneToMany(
//            fetch = FetchType.LAZY,
//            mappedBy = "orders"
//    )

    public BigDecimal getCustomerId() {
        return customerId;
    }

    public void setCustomerId(BigDecimal customerId) {
        this.customerId = customerId;
    }

    public BigDecimal getPaymentMethodId() {
        return paymentMethodId;
    }

    public void setPaymentMethodId(BigDecimal paymentMethodId) {
        this.paymentMethodId = paymentMethodId;
    }
}