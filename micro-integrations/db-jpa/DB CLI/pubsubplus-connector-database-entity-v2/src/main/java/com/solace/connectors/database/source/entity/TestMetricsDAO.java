package com.solace.connectors.database.source.entity;

import jakarta.annotation.Resource;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.List;

@Component
public class TestMetricsDAO {
    @Resource
    TestMetricsRepo repo;

    public TestMetricsDAO() {
    }

    public List<TestMetrics> findAllByRange(PageRequest pageable, String[] values) {
        return this.repo.findTestIdentificationByMetricIdGreaterThan(new BigDecimal(values[0]), pageable);

    }
}
