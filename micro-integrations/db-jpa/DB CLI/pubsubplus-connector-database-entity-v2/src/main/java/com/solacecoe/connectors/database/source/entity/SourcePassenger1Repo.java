package com.solacecoe.connectors.database.source.entity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.repository.JpaRepository;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

public interface SourcePassenger1Repo extends JpaRepository<SourcePassenger1, SourcePassenger1Id> {

    //single sequence key
    public abstract List<SourcePassenger1> findSourcePassengerByIdPassengerIdGreaterThan(BigDecimal arg1,  Pageable pageable) ;

    public abstract List<SourcePassenger1> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqual(BigDecimal min, BigDecimal contactNo, Pageable pageable) ;

    public abstract List<SourcePassenger1> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdCreatedAtGreaterThanEqual(BigDecimal min, BigDecimal contactNo, Date createdAt, Pageable pageable) ;

    public abstract List<SourcePassenger1> findSourcePassengerByIdCreatedAtGreaterThanEqual(Date createdAt, Pageable pageable);

    public abstract List<SourcePassenger1> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdBirthdayGreaterThanEqual
            (BigDecimal min, String contactNo, Date birthday, Pageable pageable);
    List<SourcePassenger1> findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(Date date1 , Date date2 , Sort sort);

    List<SourcePassenger1> findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(Date date1 , Date date2 , Pageable page);
}