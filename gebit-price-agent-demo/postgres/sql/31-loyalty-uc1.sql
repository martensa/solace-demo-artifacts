-- 31-loyalty-uc1.sql: UC1 additions to schema loyalty, owner :r_loyalty. Idempotent.
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_loyalty :role_prefix _loyalty

set role :"r_loyalty";

alter table loyalty.member add column if not exists segment_label text;

-- Anonymous weekly purchases of an article by all cardholders (seeded aggregate;
-- stands in for thousands of fictional members). week_start = first day of one of
-- the 8 seven-day windows that end yesterday (business date).
create table if not exists loyalty.article_week_stats (
  article_number   text not null references loyalty.article_ref,
  week_start       date not null,
  member_purchases int not null check (member_purchases >= 0),
  distinct_members int not null check (distinct_members >= 0),
  primary key (article_number, week_start));

reset role;
