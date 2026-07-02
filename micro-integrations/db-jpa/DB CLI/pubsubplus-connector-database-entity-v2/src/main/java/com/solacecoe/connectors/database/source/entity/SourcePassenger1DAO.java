package com.solacecoe.connectors.database.source.entity;

import jakarta.annotation.Resource;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;


@Component
public class SourcePassenger1DAO {

    @Resource
    SourcePassenger1Repo repo;

//  single sequence PK
//    public List<SourcePassenger> findAllByRange( PageRequest pageable, String[] values ){
//        return repo.findSourcePassengerByIdPassengerIdGreaterThan(new BigDecimal(values[0]) ,pageable);

//            return repo.findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqual(
//                new BigDecimal(values[0]),  new BigDecimal(values[1] ),pageable);
//        return repo.findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdCreatedAtGreaterThanEqual(
//                new BigDecimal(values[0]),  new BigDecimal(values[1] ), new Date(Long.parseLong(values[2])) ,pageable);
//        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqual(
//                new Date(Long.parseLong(values[0])) ,pageable);

//    }
    //timestamp
    public List<SourcePassenger1> findAllByRange(Sort sort, String[] values) {
        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), sort);


    }

    public List<SourcePassenger1> findAllByRange(Pageable page, String[] values) {
        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), page);
    }
}