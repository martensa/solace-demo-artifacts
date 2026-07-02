package com.solace.connectors.database.source.entity;

import org.springframework.context.MessageSource;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.List;

public interface MessagesSourceRepo extends JpaRepository<MessagesSource, Integer> {
     List<MessagesSource> findMessagesSourceByIdMessageGreaterThan(Integer var1, Pageable var2);

}