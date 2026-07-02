package com.solace.connectors.database.source.entity;

import jakarta.annotation.Resource;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.List;

@Component
public class MessagesSourceDAO {
    @Resource
    MessagesSourceRepo repo;

    public MessagesSourceDAO() {
    }

    public List<MessagesSource> findAllByRange(PageRequest pageable, String[] values) {
        return this.repo.findMessagesSourceByIdMessageGreaterThan(new Integer(values[0]), pageable);

    }
}
