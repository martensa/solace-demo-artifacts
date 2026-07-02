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

    //sequencial
    public List<<TABLE>> findAllByRange( PageRequest pageable, String[] values ){
        return repo.find<TABLE>By<TABLE_ENTITY_COLUMN>GreaterThan(new BigDecimal(values[0]) ,pageable);
    }
}

  