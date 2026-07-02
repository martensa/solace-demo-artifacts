package com.solacecoe.connectors.database.source.entity;

import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Component;

import jakarta.annotation.Resource;
import java.math.BigDecimal;
import java.util.Date;
import java.util.List;




@Component
public class SourcePassengerDAO {

    @Resource
    SourcePassengerRepo repo;

// begin single sequence PK
//    public List<SourcePassenger> findAllByRange( PageRequest pageable, String[] values ){
//        return repo.findSourcePassengerByIdPassengerIdGreaterThan(new BigDecimal(values[0]) ,pageable);
//  end single sequence PK
    //multiple columns
//            return repo.findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqual(
//                new BigDecimal(values[0]),  new BigDecimal(values[1] ),pageable);
//        return repo.findSourcePassengerByIdPassengerIdGreaterThanEqualAndIdContactNoGreaterThanEqualAndIdCreatedAtGreaterThanEqual(
//                new BigDecimal(values[0]),  new BigDecimal(values[1] ), new Date(Long.parseLong(values[2])) ,pageable);
//        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqual(
//                new Date(Long.parseLong(values[0])) ,pageable);

//    }
    //begin timestamp
    public List<SourcePassenger> findAllByRange(Sort sort, String[] values) {
        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), sort);


    }

    public List<SourcePassenger> findAllByRange(Pageable page, String[] values) {
        return repo.findSourcePassengerByIdCreatedAtGreaterThanEqualAndIdCreatedAtLessThan(
                new Date(Long.parseLong(values[0])), new Date(Long.parseLong(values[1])), page);
    }
// end timestamp
}