package com.solace.connectors.database.source.entity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface CtestRepo extends JpaRepository<Ctest, String> {

}