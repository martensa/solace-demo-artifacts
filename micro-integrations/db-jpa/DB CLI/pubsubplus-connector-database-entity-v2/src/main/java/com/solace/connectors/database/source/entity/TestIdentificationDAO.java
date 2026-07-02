package com.solace.connectors.database.source.entity;

import jakarta.annotation.Resource;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.List;

@Component
public class TestIdentificationDAO {
    @Resource
    TestIdentificationRepo repo;

    public TestIdentificationDAO() {
    }

    public List<TestIdentification> findAllByRange(PageRequest pageable, String[] values) {
        return this.repo.findTestIdentificationByIdGreaterThan(new BigDecimal(values[0]), pageable);

    }
}
