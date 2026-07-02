package com.solace.connectors.database.source.entity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.List;

public interface TestIdentificationRepo extends JpaRepository<TestIdentification, BigDecimal> {
    List<TestIdentification> findTestIdentificationByIdGreaterThan(BigDecimal var1, Pageable var2);

}