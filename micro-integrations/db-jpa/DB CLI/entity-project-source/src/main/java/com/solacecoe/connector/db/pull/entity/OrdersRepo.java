package com.solacecoe.connector.db.pull.entity;

import org.springframework.data.domain.PageRequest;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.List;

public interface OrdersRepo extends JpaRepository<Orders, BigDecimal> {

        List<Orders> findOrdersByOrderIdGreaterThan(BigDecimal id, PageRequest pageable);
}
