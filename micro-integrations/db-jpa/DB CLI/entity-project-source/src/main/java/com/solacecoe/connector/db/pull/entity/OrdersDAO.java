package com.solacecoe.connector.db.pull.entity;

import jakarta.annotation.Resource;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.List;

@Component
public class OrdersDAO {

    @Resource
    OrdersRepo repo;

    public List<Orders> findAllByRange(PageRequest pageable, String[] values) {

        return this.repo.findOrdersByOrderIdGreaterThan(new BigDecimal(values[0]), pageable);

    }
}
