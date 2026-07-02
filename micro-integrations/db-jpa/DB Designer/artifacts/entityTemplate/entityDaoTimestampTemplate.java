package com.solace.connectors.database.<CONNECTOR_TYPE>.entity;

import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;
import java.math.BigDecimal;
import java.util.Date;
import java.util.List;




@Component
public class <TABLE>DAO {

    @Resource
    <TABLE>Repo repo;

    //timestamp
    public List<<TABLE>> findAllByRange(Sort sort, String[] values) {
        return repo.find<TABLE>By<TABLE_ENTITY_COLUMN>GreaterThanEqualAnd<TABLE_ENTITY_COLUMN>LessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), sort);

    }
    public List<<TABLE>> findAllByRange(Pageable page, String[] values) {
        return repo.find<TABLE>By<TABLE_ENTITY_COLUMN>GreaterThanEqualAnd<TABLE_ENTITY_COLUMN>LessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), page);

   }
}