package com.solacecoe.connectors.database.source.entity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface HomeAddrRepo extends JpaRepository<HomeAddr, Integer> {

}