package com.solacecoe.connectors.database.source.entity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

public interface SourcePassengerRiRepo extends JpaRepository<SourcePassengerRi, SourcePassengerRiId> {


}