package com.solacecoe.connectors.database.source.entity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Sort;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

public interface SourcePassengerRepo extends JpaRepository<SourcePassenger, SourcePassengerId> {

    //begin single sequence key
    public abstract List<SourcePassenger> findSourcePassengerByIdPassengerIdGreaterThan(BigDecimal arg1,  Pageable pageable) ;
    //end single sequence key
    public abstract List<SourcePassenger> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqual(BigDecimal min, BigDecimal contactNo, Pageable pageable) ;

    public abstract List<SourcePassenger> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdCreatedAtGreaterThanEqual(BigDecimal min, BigDecimal contactNo, Date createdAt, Pageable pageable) ;

    public abstract List<SourcePassenger> findSourcePassengerByIdCreatedAtGreaterThanEqual(Date createdAt, Pageable pageable);

    public abstract List<SourcePassenger> findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdBirthdayGreaterThanEqual
            (BigDecimal min, String contactNo, Date birthday, Pageable pageable);

    //begin timestamp
    List<SourcePassenger> findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(Date date1 , Date date2 , Sort sort);

    List<SourcePassenger> findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(Date date1 , Date date2 , Pageable page);
    //end timestamp
}