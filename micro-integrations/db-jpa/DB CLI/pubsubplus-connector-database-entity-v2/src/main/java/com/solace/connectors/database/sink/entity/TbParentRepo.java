package com.solace.connectors.database.sink.entity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;


@Repository
public interface TbParentRepo extends JpaRepository<TbParent, String>{
    
}
