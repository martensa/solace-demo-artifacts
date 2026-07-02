package com.solace.connectors.database.<CONNECTOR_TYPE>.entity;

import org.springframework.data.jpa.repository.JpaRepository;

import org.springframework.data.domain.Pageable;

import org.springframework.data.domain.Sort;

import java.lang.*;

import java.util.*;

import java.math.*;



public interface <TABLE_REPO> extends JpaRepository<<TABLE>, <TABLE_ID>> {

      public abstract List<<TABLE>> find<TABLE>By<TABLE_ENTITY_COLUMN>GreaterThan(BigDecimal arg1,  Pageable pageable) ;

}

